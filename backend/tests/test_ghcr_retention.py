from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ghcr-retention.py"

# Host-only, like test_env_surface_drift.py and test_privileged_script_modes.py: the
# backend image contains only `backend/`, so under `dev-docker.sh exec backend pytest`
# this file sits at /app/tests/ and `parents[2]` is `/`. Without this guard the fixture
# would look for /scripts/ghcr-retention.py and redden the whole Docker suite. The script
# under test is release CI tooling that never ships inside the image, so there is nothing
# to resolve there - it is genuinely a repo-layout test, not an application test.
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)


@pytest.fixture(scope="module")
def retention():
    spec = importlib.util.spec_from_file_location("ghcr_retention_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def version(retention):
    def make(version_id: str, digest: str, *tags: str):
        return retention.PackageVersion(version_id, digest, frozenset(tags))

    return make


@pytest.fixture
def protected(retention):
    return retention.retention_identifiers(
        "1.4.0-main.42.abc123",
        "sha-abc123",
        "1.4",
        "1.3.9-main.41.def456",
    )


def test_kept_tagged_root_keeps_untagged_children(
    retention, version, protected
):
    versions = (
        version("1", "sha256:root", "1.4.0-main.42.abc123"),
        version("2", "sha256:platform"),
        version("3", "sha256:attestation"),
        version("4", "sha256:stale"),
    )
    children = {
        "sha256:root": {"sha256:platform", "sha256:attestation"},
    }

    assert retention.digests_to_delete(versions, protected, children) == {
        "sha256:stale"
    }


def test_genuinely_stale_untagged_version_is_deleted(retention, version, protected):
    versions = (
        version("1", "sha256:root", "1.4.0-main.42.abc123"),
        version("2", "sha256:stale"),
    )

    assert retention.digests_to_delete(
        versions, protected, {"sha256:root": set()}
    ) == {"sha256:stale"}


def test_child_discovery_failure_skips_every_deletion_for_package(
    retention, protected
):
    listing = "1\tsha256:root\t1.4.0-main.42.abc123\n2\tsha256:stale\t\n"
    deleted = []

    def runner(command):
        if command[:3] == ("gh", "api", "--paginate"):
            return listing
        if command[:5] == (
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            "--raw",
        ):
            raise retention.CommandError("registry unavailable")
        if "DELETE" in command:
            deleted.append(command)
            return ""
        raise AssertionError(command)

    cleaned = retention.clean_package(
        "spaceworks-hq",
        "spaceworks-backend",
        protected,
        runner=runner,
        sleeper=lambda _seconds: None,
    )

    assert cleaned is False
    assert deleted == []


def test_previous_release_and_its_children_survive(retention, version, protected):
    versions = (
        version("1", "sha256:previous", "1.3.9-main.41.def456"),
        version("2", "sha256:previous-platform"),
        version("3", "sha256:stale"),
    )
    children = {"sha256:previous": {"sha256:previous-platform"}}

    assert retention.digests_to_delete(versions, protected, children) == {
        "sha256:stale"
    }


def test_main_latest_and_sha_tagged_versions_survive(retention, version, protected):
    versions = (
        version("1", "sha256:main", "main"),
        version("2", "sha256:latest", "latest"),
        version("3", "sha256:sha", "sha-abc123"),
        version("4", "sha256:stale", "old-tag"),
    )

    assert retention.digests_to_delete(
        versions,
        protected,
        {
            "sha256:main": set(),
            "sha256:latest": set(),
            "sha256:sha": set(),
        },
    ) == {"sha256:stale"}


# The tests above exercise the pure decision. These cover the three I/O seams where a
# mistake is just as fatal and just as invisible: turning a digest decision back into the
# version ids that get DELETEd, parsing a buildx index, and parsing the GHCR listing.


def test_clean_package_deletes_only_the_stale_version_id(retention, protected):
    """The decision is by digest, but the API deletes by id - the mapping must hold."""
    listing = (
        "11\tsha256:root\t1.4.0-main.42.abc123\n"
        "22\tsha256:platform\t\n"
        "33\tsha256:attestation\t\n"
        "44\tsha256:stale\t\n"
    )
    index = (
        '{"manifests": [{"digest": "sha256:platform"},'
        ' {"digest": "sha256:attestation"}]}'
    )
    deleted = []

    def runner(command):
        if command[:3] == ("gh", "api", "--paginate"):
            return listing
        if command[:5] == ("docker", "buildx", "imagetools", "inspect", "--raw"):
            return index
        if "DELETE" in command:
            deleted.append(command[-1])
            return ""
        raise AssertionError(command)

    cleaned = retention.clean_package(
        "spaceworks-hq",
        "spaceworks-backend",
        protected,
        runner=runner,
        sleeper=lambda _seconds: None,
    )

    assert cleaned is True
    assert len(deleted) == 1, deleted
    assert deleted[0].endswith("/versions/44"), deleted
    # The outage in one assertion: the untagged children must never be deleted.
    assert not any(
        endpoint.endswith(("/versions/22", "/versions/33")) for endpoint in deleted
    )


def test_inspect_children_reads_an_index_and_tolerates_a_plain_manifest(retention):
    def index_runner(_command):
        return (
            '{"mediaType": "application/vnd.oci.image.index.v1+json",'
            ' "manifests": [{"digest": "sha256:a"}, {"digest": "sha256:b"}]}'
        )

    assert retention.inspect_children(
        "ghcr.io/o/p", "sha256:root", runner=index_runner, sleeper=lambda _s: None
    ) == {"sha256:a", "sha256:b"}

    def plain_runner(_command):
        return '{"mediaType": "application/vnd.oci.image.manifest.v1+json"}'

    assert (
        retention.inspect_children(
            "ghcr.io/o/p", "sha256:leaf", runner=plain_runner, sleeper=lambda _s: None
        )
        == frozenset()
    )


def test_inspect_children_fails_closed_on_unparseable_output(retention):
    with pytest.raises(retention.CommandError):
        retention.inspect_children(
            "ghcr.io/o/p",
            "sha256:root",
            runner=lambda _command: "not json",
            sleeper=lambda _s: None,
        )


def test_list_package_versions_parses_digests_and_untagged_rows(retention):
    listing = "11\tsha256:root\t1.4.0,latest\n22\tsha256:child\t\n"

    versions = retention.list_package_versions(
        "spaceworks-hq",
        "spaceworks-backend",
        runner=lambda _command: listing,
        sleeper=lambda _s: None,
    )

    assert versions[0].digest == "sha256:root"
    assert versions[0].tags == frozenset({"1.4.0", "latest"})
    # An untagged child must parse as a real row, not be dropped: dropping it would make
    # it invisible to retention and therefore undeletable-and-unprotectable alike.
    assert versions[1] == retention.PackageVersion("22", "sha256:child", frozenset())
