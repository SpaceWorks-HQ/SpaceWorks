import uuid
from pathlib import Path

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.backup import storage
from apps.backup.archive_import import import_disaster_archive
from apps.backup.digests import SUPPORTED_ARCHIVE_FORMATS
from apps.backup.models import (
    BackupArchive,
    DeploymentRecoveryState,
    RestoreOperation,
)
from apps.backup.restore_services import request_restore
from apps.tenant_migration import archive_envelope, tenant_dump_envelope
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_lineage import FORMAT
from apps.tenant_migration.tenant_dump_manifest import _valid_key_inventory


pytestmark = pytest.mark.django_db


def _superuser():
    return User.objects.create_superuser(
        username="d8-format-operator", password="not-a-secret"
    )


def test_lane_d_format_is_disjoint_from_deployment_and_obsolete_formats():
    assert FORMAT == "spaceworks-tenant-dump-v1"
    assert FORMAT not in SUPPORTED_ARCHIVE_FORMATS
    assert all(value.startswith("spaceworks-phase5a-") for value in SUPPORTED_ARCHIVE_FORMATS)
    assert FORMAT != archive_envelope.FORMAT
    assert archive_envelope.FORMAT == "spaceworks-tenant-migration-v1"


def test_host_import_rejects_lane_d_before_storage_or_database_mutation(
    monkeypatch, tmp_path
):
    artifact = tmp_path / "tenant-dump.age"
    artifact.write_bytes(b"sealed tenant dump")
    uploads = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: uploads.append(args))

    with pytest.raises(ValidationError, match="Phase 5A full-deployment"):
        import_disaster_archive(
            _superuser(),
            artifact,
            {
                "archive_id": str(uuid.uuid4()),
                "format": FORMAT,
                "scope": "deployment",
                "age_encrypted": True,
            },
            expected_sha256="0" * 64,
        )

    assert uploads == []
    assert BackupArchive.objects.count() == 0
    assert RestoreOperation.objects.count() == 0


def test_ordinary_restore_request_rejects_lane_d_before_state_mutation():
    actor = _superuser()
    DeploymentRecoveryState.load()
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=actor,
        status=BackupArchive.Status.AVAILABLE,
        object_key=f"tenant-dumps/{uuid.uuid4()}.age",
        manifest={"format": FORMAT},
        age_encrypted=True,
        expires_at=timezone.now(),
    )

    with pytest.raises(ValidationError, match="Lane D|Phase 5A|format"):
        request_restore(actor, archive, RestoreOperation.Kind.DISASTER)

    assert RestoreOperation.objects.count() == 0
    assert DeploymentRecoveryState.load().mode == DeploymentRecoveryState.Mode.NORMAL


@pytest.mark.parametrize(
    "forbidden_member",
    (
        "keys/env.json",
        "keys/deks.json",
        "keys/plaintext-dek.bin",
        "deployment/continuity-secrets.json",
    ),
)
def test_lane_d_content_ledger_rejects_each_forbidden_secret_member(
    tmp_path, forbidden_member
):
    member = tmp_path.joinpath(*forbidden_member.split("/"))
    member.parent.mkdir(parents=True, exist_ok=True)
    member.write_bytes(b"forbidden-secret-material")

    with pytest.raises(TenantDumpVerificationError, match="forbidden|not permitted|secret|DEK"):
        tenant_dump_envelope.build_tenant_content_ledger(
            tmp_path, source_pii_mode="plaintext"
        )


def test_source_broker_wrapped_dek_value_is_not_an_allowed_inventory_field():
    inventory = [{
        "source_key_row_id": 1,
        "makerspace_id": 7,
        "version": 1,
        "status": "active",
        "source_broker_backend": "local",
        "source_broker_key_id": "source-key",
        "source_wrapped_dek_sha256": "a" * 64,
        "wrapped_dek": "source-broker-ciphertext",
    }]

    assert _valid_key_inventory(inventory, 7) is False


def test_lane_d_outer_manifest_has_a_strict_pre_decryption_allowlist():
    builder = getattr(tenant_dump_envelope, "build_outer_manifest", None)
    assert callable(builder), "Lane D needs a separately readable outer-manifest builder."
    manifest = builder(
        format=FORMAT,
        version=1,
        artifact_id="artifact",
        capture_id="capture",
        outer_recipient_fingerprints=["outer"],
        tenant_dek_recipient_fingerprints=["tenant"],
        encrypted_members=[{"path": "payload.age", "sha256": "a" * 64, "size": 1}],
        source_build={"source_hash": "b" * 64},
        postgres_major=16,
        compatibility={},
    )

    assert set(manifest) == {
        "format", "version", "artifact_id", "capture_id",
        "outer_recipient_fingerprints", "tenant_dek_recipient_fingerprints",
        "encrypted_members", "source_build", "postgres_major", "compatibility",
    }
    assert not ({"rows", "object_keys", "user_closure", "deks"} & set(manifest))


def test_lane_d_has_no_shared_deployment_secret_policy_or_include_secrets_switch():
    app_root = Path(__file__).resolve().parents[2] / "apps" / "tenant_migration"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(app_root.glob("tenant_dump*.py"))
    )

    assert "include_secrets" not in sources
    assert "CONTINUITY_KEYS" not in sources
    for deployment_policy_module in (
        "apps.backup.archive_payload",
        "apps.backup.outer_manifest",
        "apps.backup.import_preflight",
        "apps.backup.archive_import",
        "apps.backup.restore_services",
    ):
        assert deployment_policy_module not in sources
