from pathlib import Path
from types import SimpleNamespace
import json
import uuid

import pytest
from django.utils import timezone

from apps.backup import outer_manifest
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.user_closure import user_closure_digest
from tests.backup.e7_manifest_test_facts import (
    bind_source_partition_proof,
    empty_reservation_capture,
)


pytestmark = pytest.mark.django_db


def _capture(capture_id, makerspace_id, slice_digest="2" * 64):
    component = outer_manifest.component_id(capture_id, "slice", makerspace_id)
    frozen = SimpleNamespace(makerspace_id=makerspace_id, custody_state="healthy")
    return SimpleNamespace(
        capture_id=capture_id,
        frozen_population_ids=(makerspace_id,),
        frozen_slices=(frozen,),
        expected_main_ledger={"catalog": "verified"},
        source_catalog_digest="a" * 64,
        platform_recipients=frozenset({f"age1plat{uuid.uuid4().hex}"}),
        reservation_capture=empty_reservation_capture(),
        source_partition_proof=None,
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
        "build": {"git_sha": "e5-build", "source_hash": "e5-source"},
        "oci_digest": "sha256:" + "e" * 64,
        "postgres": {
            "source_server_major": 16,
            "client": "pg_dump (PostgreSQL) 16.10",
            "supported_source_majors": [14, 15, 16, 17],
        },
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
    bind_source_partition_proof(capture, archive, detailed, tmp_path)

    manifest = outer_manifest.build_outer_manifest(
        archive=archive,
        capture=capture,
        detailed_manifest=detailed,
        root=tmp_path,
    )
    encoded = json.dumps(manifest, sort_keys=True).encode()

    assert set(manifest) == {
        "format", "protocol_version", "artifact_id", "capture_id",
        "source_timestamp", "build_identity", "postgres", "makerspace_sets",
        "main_component", "slice_components", "object_ledgers",
        "content_ledgers", "reservation_commitments", "broad_fence_scopes",
        "relationship_fence_scopes", "object_namespace_fences",
        "sequence_reservations", "reservation_salt",
        "reservation_registry_digest", "source_partition_proof",
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
    assert manifest["postgres"]["source_server_major"] == 16
    assert outer_manifest.verify_outer_manifest(manifest) is True

    tampered = {
        **manifest,
        "postgres": {**manifest["postgres"], "source_server_major": 17},
    }
    with pytest.raises(BackupBuildError, match="signature is invalid"):
        outer_manifest.verify_outer_manifest(tampered)


@pytest.mark.parametrize("postgres_major", (None, True, 0, 9, 100, "16"))
def test_outer_manifest_rejects_missing_mistyped_or_implausible_postgres_major(
    tmp_path, postgres_major
):
    archive = SimpleNamespace(pk=uuid.uuid4())
    capture = _capture(uuid.uuid4(), 41)
    Path(tmp_path, "database.dump").write_bytes(b"readable main")
    detailed = _detailed("ordinary-object-key")
    bind_source_partition_proof(capture, archive, detailed, tmp_path)
    manifest = outer_manifest.build_outer_manifest(
        archive=archive,
        capture=capture,
        detailed_manifest=detailed,
        root=tmp_path,
    )
    manifest.pop("archive_signature")
    if postgres_major is None:
        manifest.pop("postgres")
    else:
        manifest["postgres"] = {
            **manifest["postgres"],
            "source_server_major": postgres_major,
        }

    with pytest.raises(BackupBuildError, match="structure is invalid"):
        outer_manifest.validate_unsigned_manifest(
            manifest, protocol_version=outer_manifest.PROTOCOL_VERSION
        )


def test_outer_manifest_rejects_missing_source_build_identity(tmp_path):
    archive = SimpleNamespace(pk=uuid.uuid4())
    capture = _capture(uuid.uuid4(), 41)
    Path(tmp_path, "database.dump").write_bytes(b"readable main")
    detailed = _detailed("ordinary-object-key")
    bind_source_partition_proof(capture, archive, detailed, tmp_path)
    manifest = outer_manifest.build_outer_manifest(
        archive=archive,
        capture=capture,
        detailed_manifest=detailed,
        root=tmp_path,
    )
    manifest.pop("archive_signature")
    manifest["build_identity"] = {
        **manifest["build_identity"], "build": {"git_sha": "unidentified"}
    }

    with pytest.raises(BackupBuildError, match="structure is invalid"):
        outer_manifest.validate_unsigned_manifest(
            manifest, protocol_version=outer_manifest.PROTOCOL_VERSION
        )


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


def test_outer_manifest_rejects_non_positive_makerspace_identity(tmp_path):
    archive = SimpleNamespace(pk=uuid.uuid4())
    capture = _capture(uuid.uuid4(), 0)
    Path(tmp_path, "database.dump").write_bytes(b"readable main")
    detailed = _detailed("ordinary-object-key")
    bind_source_partition_proof(capture, archive, detailed, tmp_path)

    with pytest.raises(BackupBuildError, match="structure is invalid"):
        outer_manifest.build_outer_manifest(
            archive=archive,
            capture=capture,
            detailed_manifest=detailed,
            root=tmp_path,
        )
