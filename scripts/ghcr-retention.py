#!/usr/bin/env python3
"""Delete stale GHCR versions without orphaning retained OCI indexes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import NamedTuple


class PackageVersion(NamedTuple):
    version_id: str
    digest: str
    tags: frozenset[str]


class CommandError(RuntimeError):
    """An external command failed or returned unusable data."""


CommandRunner = Callable[[Sequence[str]], str]
Sleeper = Callable[[float], None]


def retention_identifiers(
    version: str,
    sha_tag: str,
    series: str,
    previous_version: str,
) -> frozenset[str]:
    """Return the exact tag names protected by the release workflow."""
    return frozenset(
        identifier
        for identifier in (
            version,
            sha_tag,
            series,
            previous_version,
            "main",
            "latest",
        )
        if identifier
    )


def retained_root_digests(
    versions: Iterable[PackageVersion],
    protected_tags: frozenset[str],
) -> frozenset[str]:
    """Find tagged manifests that are roots of retained OCI graphs."""
    return frozenset(
        version.digest for version in versions if version.tags & protected_tags
    )


def digests_to_delete(
    versions: Iterable[PackageVersion],
    protected_tags: frozenset[str],
    children_by_root: Mapping[str, Iterable[str]],
) -> frozenset[str]:
    """Pure retention decision from a version listing and discovered child maps."""
    version_list = tuple(versions)
    roots = retained_root_digests(version_list, protected_tags)
    children = {
        child_digest
        for root_digest in roots
        for child_digest in children_by_root.get(root_digest, ())
    }
    return frozenset(
        version.digest
        for version in version_list
        if version.digest not in roots | children
    )


def run_command(command: Sequence[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        raise CommandError(f"Could not run {command[0]}: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise CommandError(f"{' '.join(command)} failed: {detail}")
    return completed.stdout


def run_with_retry(
    command: Sequence[str],
    description: str,
    *,
    runner: CommandRunner = run_command,
    sleeper: Sleeper = time.sleep,
) -> str:
    """Match the workflow's four attempts with 2, 4, and 6 second backoff."""
    last_error: CommandError | None = None
    for attempt in range(1, 5):
        try:
            return runner(command)
        except CommandError as error:
            last_error = error
            if attempt == 4:
                break
            print(
                f"{description} failed (attempt {attempt}/4); retrying.",
                file=sys.stderr,
            )
            sleeper(attempt * 2)
    assert last_error is not None
    raise last_error


def list_package_versions(
    owner: str,
    package: str,
    *,
    runner: CommandRunner = run_command,
    sleeper: Sleeper = time.sleep,
) -> tuple[PackageVersion, ...]:
    # GHCR exposes the manifest digest as `name`; tags alone cannot connect an
    # index to the untagged platform and attestation manifests it references.
    output = run_with_retry(
        (
            "gh",
            "api",
            "--paginate",
            f"orgs/{owner}/packages/container/{package}/versions?per_page=100",
            "--jq",
            '.[] | [.id, .name, (.metadata.container.tags // [] | join(","))] | @tsv',
        ),
        f"Listing {package} versions",
        runner=runner,
        sleeper=sleeper,
    )
    versions: list[PackageVersion] = []
    for line in output.splitlines():
        if not line:
            continue
        fields = line.split("\t", 2)
        if len(fields) != 3 or not fields[0] or not fields[1]:
            raise CommandError(f"Malformed GHCR version row for {package}: {line!r}")
        tags = frozenset(filter(None, fields[2].split(",")))
        versions.append(PackageVersion(fields[0], fields[1], tags))
    return tuple(versions)


def inspect_children(
    image: str,
    digest: str,
    *,
    runner: CommandRunner = run_command,
    sleeper: Sleeper = time.sleep,
) -> frozenset[str]:
    output = run_with_retry(
        ("docker", "buildx", "imagetools", "inspect", "--raw", f"{image}@{digest}"),
        f"Inspecting {image}@{digest}",
        runner=runner,
        sleeper=sleeper,
    )
    try:
        document = json.loads(output)
        manifests = document.get("manifests", [])
        if not isinstance(manifests, list):
            raise ValueError("manifests is not a list")
        children = set()
        for manifest in manifests:
            child_digest = manifest.get("digest") if isinstance(manifest, dict) else None
            if not isinstance(child_digest, str) or not child_digest:
                raise ValueError("a child manifest has no digest")
            children.add(child_digest)
    except (json.JSONDecodeError, AttributeError, ValueError) as error:
        raise CommandError(f"Invalid manifest JSON for {image}@{digest}: {error}") from error
    return frozenset(children)


def delete_package_version(
    owner: str,
    package: str,
    version_id: str,
    *,
    runner: CommandRunner = run_command,
    sleeper: Sleeper = time.sleep,
) -> None:
    run_with_retry(
        (
            "gh",
            "api",
            "--method",
            "DELETE",
            f"orgs/{owner}/packages/container/{package}/versions/{version_id}",
        ),
        f"Deleting {package} version {version_id}",
        runner=runner,
        sleeper=sleeper,
    )


def clean_package(
    owner: str,
    package: str,
    protected_tags: frozenset[str],
    *,
    runner: CommandRunner = run_command,
    sleeper: Sleeper = time.sleep,
) -> bool:
    try:
        versions = list_package_versions(
            owner, package, runner=runner, sleeper=sleeper
        )
    except CommandError as error:
        print(f"::warning::Could not list {package} versions after retries: {error}")
        return False

    image = f"ghcr.io/{owner}/{package}"
    children_by_root: dict[str, frozenset[str]] = {}
    for root_digest in sorted(retained_root_digests(versions, protected_tags)):
        try:
            children_by_root[root_digest] = inspect_children(
                image, root_digest, runner=runner, sleeper=sleeper
            )
        except CommandError as error:
            # Deleting on an incomplete graph is precisely how tagged indexes became
            # dangling. One unknown root therefore vetoes every deletion in this package.
            print(
                f"::warning::Skipping all {package} deletions because child "
                f"discovery failed for {root_digest}: {error}"
            )
            return False

    stale_digests = digests_to_delete(versions, protected_tags, children_by_root)
    for version in versions:
        if version.digest not in stale_digests:
            continue
        try:
            delete_package_version(
                owner,
                package,
                version.version_id,
                runner=runner,
                sleeper=sleeper,
            )
        except CommandError as error:
            print(
                f"::warning::Could not remove {package} version "
                f"{version.version_id} after retries: {error}"
            )
    return True


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retain current GHCR release graphs and delete stale versions."
    )
    parser.add_argument("--owner", required=True)
    parser.add_argument("--package", action="append", required=True, dest="packages")
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha-tag", required=True)
    parser.add_argument("--series", required=True)
    parser.add_argument("--previous-version", default="")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    protected_tags = retention_identifiers(
        args.version, args.sha_tag, args.series, args.previous_version
    )
    for package in args.packages:
        clean_package(args.owner, package, protected_tags)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
