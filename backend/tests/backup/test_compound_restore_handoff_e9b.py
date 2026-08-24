from types import SimpleNamespace
from datetime import timedelta
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO
import pytest
from django.utils import timezone

from apps.backup import backup_control_preflight
from apps.backup.models import BackupArchive, RestoreOperation
from tests.backup.import_preflight_test_support import make_import_fixture


pytestmark = pytest.mark.django_db


def _restore(actor, fixture):
    archive = BackupArchive.objects.create(
        id=uuid.UUID(fixture.manifest["artifact_id"]),
        scope=BackupArchive.Scope.DEPLOYMENT,
        status=BackupArchive.Status.AVAILABLE,
        age_encrypted=True,
        archive_sha256=fixture.expected_sha256,
        manifest=fixture.manifest,
        object_key="test/compound.tar.age",
        requested_by=actor,
        expires_at=timezone.now() + timedelta(days=1),
    )
    return RestoreOperation.objects.create(
        archive=archive,
        kind=RestoreOperation.Kind.DISASTER,
        requested_by=actor,
    )


def test_compound_backup_control_reaches_validated_coordinator_handoff(
    monkeypatch, tmp_path, django_user_model
):
    fixture = make_import_fixture(tmp_path)
    actor = django_user_model.objects.create_superuser(
        username="compound-handoff", password="not-used"
    )
    restore = _restore(actor, fixture)
    monkeypatch.setattr(
        backup_control_preflight,
        "validate_import_preflight",
        lambda **_kwargs: SimpleNamespace(
            manifest=fixture.manifest,
            archive_sha256=fixture.expected_sha256,
        ),
    )
    stdout = StringIO()

    call_command(
        "backup_control", "preflight", str(restore.pk),
        manifest=str(fixture.manifest_file), bundle=str(tmp_path),
        encrypted_file=str(fixture.encrypted),
        decrypted_bundle=str(fixture.bundle),
        continuity_secrets=str(fixture.secrets_file), stdout=stdout,
    )

    assert stdout.getvalue().strip().endswith("compound-coordinator-ready")


def test_legacy_path_refusal_names_missing_compound_handoff_inputs(
    tmp_path, django_user_model
):
    fixture = make_import_fixture(tmp_path)
    actor = django_user_model.objects.create_superuser(
        username="compound-specific-refusal", password="not-used"
    )
    restore = _restore(actor, fixture)

    with pytest.raises(CommandError, match="scripts/restore.sh legacy path"):
        call_command(
            "backup_control", "preflight", str(restore.pk),
            manifest=str(fixture.manifest_file), bundle=str(tmp_path),
        )
