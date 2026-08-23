from pathlib import Path
from types import SimpleNamespace
import json
import uuid

import pytest
from django.utils import timezone

from apps.backup import outer_manifest
from apps.backup.user_closure import user_closure_digest


pytestmark = pytest.mark.django_db


def _capture(capture_id, makerspace_id, slice_digest="2" * 64):
    component = outer_manifest.component_id(capture_id, "slice", makerspace_id)
    frozen = SimpleNamespace(makerspace_id=makerspace_id, custody_state="healthy")
    return SimpleNamespace(
        capture_id=capture_id,
        frozen_population_ids=(makerspace_id,),
        frozen_slices=(frozen,),
        expected_main_ledger={"catalog": "verified"},
        user_closure_digest=user_closure_digest(
            (("stubbed", "17", "sovereign-global-user-reference"),)
        ),
        slice_entries=[{
            "component_id": component,
            "makerspace_id": makerspace_id,
            "path": f"slices/{component}.tar.age",
            "size_bytes": 23,
            "ciphertext_sha256": slice_digest,
            "recipient_fingerprints": ["3" * 64, "4" * 64],
            "object_ledger_count": 1,
            "object_ledger_digest": "5" * 64,
            "content_ledger_count": 4,
            "content_ledger_digest": "8" * 64,
        }],
    )


def _detailed(secret_object_key):
    return {
        "format": "spaceworks-phase5a-v3",
        "snapshot_at": timezone.now().isoformat(),
        "build": {"git_sha": "e5-build"},
        "oci_digest": "sha256:e5",
        "recipient_fingerprints": ["6" * 64],
        "storage": {"objects": [{
            "key": secret_object_key,
            "size": 7,
            "sha256": "7" * 64,
        }]},
        "contents": [{
            "path": f"objects/private/{secret_object_key}",
            "size": 7,
            "sha256": "7" * 64,
        }],
    }


def test_readable_outer_manifest_contains_only_non_disclosing_component_facts(tmp_path):
    raw_object_key = "raw-low-entropy-object-key-e5"
    raw_reservation = "short-unique-value-e5"
    tenant_plaintext = "sovereign-tenant-plaintext-e5"
    archive = SimpleNamespace(pk=uuid.uuid4())
    capture_id = uuid.uuid4()
    capture = _capture(capture_id, 41)
    Path(tmp_path, "database.dump").write_bytes(b"readable main")
    detailed = _detailed(raw_object_key)
    detailed["reservation"] = raw_reservation
    detailed["tenant_name"] = tenant_plaintext

    manifest = outer_manifest.build_outer_manifest(
        archive=archive,
        capture=capture,
        detailed_manifest=detailed,
        root=tmp_path,
    )
    encoded = json.dumps(manifest, sort_keys=True).encode()

    assert set(manifest) == {
        "format", "protocol_version", "artifact_id", "capture_id",
        "source_timestamp", "build_identity", "makerspace_sets",
        "main_component", "slice_components", "object_ledgers",
        "content_ledgers", "reservation_commitments", "broad_fence_scopes",
        "not_restored_seeds", "user_closure_digest", "archive_signature",
        "archive_id", "scope", "age_encrypted", "snapshot_at", "build",
        "oci_digest", "covered_makerspace_ids", "excluded_makerspace_ids",
        "partial", "recipient_fingerprints", "slices", "contents",
    }
    for forbidden in (raw_object_key, raw_reservation, tenant_plaintext):
        assert forbidden.encode() not in encoded
    assert manifest["slice_components"][0]["makerspace_id"] == 41
    assert manifest["slice_components"][0]["ciphertext_sha256"] == "2" * 64
    assert manifest["slice_components"][0]["recipient_fingerprints"] == [
        "3" * 64, "4" * 64
    ]
    assert "public_key" not in manifest["archive_signature"]
    assert outer_manifest.verify_outer_manifest(manifest) is True


@pytest.mark.parametrize(
    ("entries", "version"),
    (
        ((("included", "9", "member-owned"),), 2),
        ((("included", "10", "member-owned"),), 1),
        ((("stubbed", "9", "member-owned"),), 1),
        ((("included", "9", "shared-authority"),), 1),
    ),
)
def test_user_closure_digest_changes_for_every_semantic_input(entries, version):
    baseline = user_closure_digest(
        (("included", "9", "member-owned"),), encoding_version=1
    )
    assert user_closure_digest(entries, encoding_version=version) != baseline


def test_component_ids_bind_capture_kind_and_makerspace():
    first = uuid.uuid4()
    second = uuid.uuid4()
    values = {
        outer_manifest.component_id(first, "main"),
        outer_manifest.component_id(first, "slice", 1),
        outer_manifest.component_id(first, "slice", 2),
        outer_manifest.component_id(second, "slice", 1),
    }
    assert len(values) == 4
