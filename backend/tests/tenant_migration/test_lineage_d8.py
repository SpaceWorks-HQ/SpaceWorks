from types import SimpleNamespace
import uuid

import pytest

from apps.tenant_migration import tenant_dump_lineage as lineage
from apps.tenant_migration.tenant_dump_errors import (
    TenantDumpPublicationRefused,
    TenantDumpVerificationError,
)
from apps.tenant_migration.tenant_dump_publication import _verify_publication_lineage


def _capture():
    capture_id = uuid.uuid4()
    digest = "a" * 64
    capture = SimpleNamespace(
        pk=capture_id,
        database_image_sha256="b" * 64,
        object_ledger_sha256="c" * 64,
        derivation_policy_sha256="d" * 64,
        parent_database_sha256="b" * 64,
        parent_object_ledger_sha256="c" * 64,
        content_ledger=[{"path": "database.dump", "size": 1, "sha256": digest}],
    )
    capture.manifest = {
        "format": lineage.FORMAT,
        "capture_id": str(capture_id),
        "lineage": {
            "database_image_sha256": capture.database_image_sha256,
            "object_ledger_sha256": capture.object_ledger_sha256,
            "derivation_policy_sha256": capture.derivation_policy_sha256,
        },
        "contents": capture.content_ledger,
    }
    return capture


@pytest.mark.parametrize(
    "parent_field",
    ("parent_database_sha256", "parent_object_ledger_sha256"),
)
def test_publication_requires_each_parent_digest_to_equal_the_capture(
    monkeypatch, parent_field
):
    capture = _capture()
    setattr(capture, parent_field, "f" * 64)
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication.verify_artifact_lineage",
        lambda *_args: True,
    )

    with pytest.raises(TenantDumpPublicationRefused, match="parent lineage"):
        _verify_publication_lineage(capture)


def test_matching_database_and_object_parent_digests_are_accepted(monkeypatch):
    capture = _capture()
    checked = []
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_publication.verify_artifact_lineage",
        lambda row, manifest: checked.append((row, manifest)) or True,
    )

    _verify_publication_lineage(capture)

    assert checked == [(capture, capture.manifest)]


@pytest.mark.parametrize(
    "forbidden",
    ("companion_slice", "companion_slice_id", "lossless_slice"),
)
def test_tenant_exit_manifest_rejects_every_companion_slice_declaration(
    monkeypatch, forbidden
):
    capture = _capture()
    capture.manifest[forbidden] = False
    monkeypatch.setattr(lineage, "verify_envelope_custody_manifest", lambda *_args: True)

    with pytest.raises(TenantDumpVerificationError, match="companion slice"):
        lineage.verify_artifact_lineage(capture, capture.manifest)


def test_derivation_policy_commits_to_no_companion_slice():
    with_companion = lineage.canonical_digest({
        "format": lineage.FORMAT,
        "policy_version": lineage.DERIVATION_POLICY_VERSION,
        "catalog_digest": lineage.CATALOG_SCHEMA_SHA256,
        "source_encryption_mode": True,
        "companion_slice": True,
    })

    assert lineage.derivation_policy_digest(source_encryption_mode=True) != with_companion
