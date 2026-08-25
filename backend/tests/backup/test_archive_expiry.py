import json
from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.backup.models import BackupArchive, PlatformBackupSettings, RestoreOperation
from apps.backup.restore_control_records import rehydrate_control_record
from apps.backup.restore_services import request_restore


pytestmark = pytest.mark.django_db


def _mid_build_archive():
    archive_id = uuid.uuid4()
    return BackupArchive.objects.create(
        id=archive_id,
        scope=BackupArchive.Scope.DEPLOYMENT,
        status=BackupArchive.Status.RUNNING,
        object_key=f"backup-archives/deployment/{archive_id}.tar.age",
        build_holder=uuid.uuid4(),
    )


def test_available_archive_requires_expiry():
    with pytest.raises(IntegrityError), transaction.atomic():
        BackupArchive.objects.create(
            scope=BackupArchive.Scope.DEPLOYMENT,
            status=BackupArchive.Status.AVAILABLE,
            object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
            expires_at=None,
        )


def test_rehydration_finalizes_mid_build_archive_with_retention_expiry(tmp_path):
    archive = _mid_build_archive()
    settings_row = PlatformBackupSettings.load()
    settings_row.retention_days = 7
    settings_row.save(update_fields=("retention_days", "updated_at"))
    control = tmp_path / "control.json"
    manifest = tmp_path / "manifest.json"
    control.write_text(json.dumps({"decision": "proceed"}), encoding="utf-8")
    manifest.write_text(json.dumps({"archive_id": str(archive.pk)}), encoding="utf-8")
    before = timezone.now()

    rehydrate_control_record(
        uuid.uuid4(),
        {
            "archive_id": str(archive.pk),
            "kind": RestoreOperation.Kind.DISASTER,
            "control_record": str(control),
            "manifest": str(manifest),
        },
    )

    archive.refresh_from_db()
    assert archive.status == BackupArchive.Status.AVAILABLE
    assert before + timedelta(days=6, hours=23) < archive.expires_at
    assert archive.expires_at < before + timedelta(days=7, minutes=1)


def test_archive_expiry_cannot_be_replaced_after_finalization():
    archive = _mid_build_archive()
    expires_at = timezone.now() + timedelta(days=1)
    BackupArchive.objects.filter(pk=archive.pk).update(
        status=BackupArchive.Status.AVAILABLE,
        expires_at=expires_at,
    )

    with pytest.raises(DatabaseError, match="immutable backup archive expiry"), transaction.atomic():
        BackupArchive.objects.filter(pk=archive.pk).update(
            expires_at=expires_at + timedelta(days=1)
        )


def test_frozen_access_decision_cannot_follow_a_later_live_switch():
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        superadmin_access_at_decision=False,
    )
    with pytest.raises(DatabaseError, match="immutable backup archive access"), transaction.atomic():
        BackupArchive.objects.filter(pk=archive.pk).update(
            superadmin_access_at_decision=True
        )


def test_restore_boundary_rejects_available_archive_without_expiry():
    archive = SimpleNamespace(
        scope=BackupArchive.Scope.DEPLOYMENT,
        status=BackupArchive.Status.AVAILABLE,
        expires_at=None,
        manifest={"format": "spaceworks-phase5a-v2"},
    )
    with pytest.raises(ValidationError, match="not available"):
        request_restore(SimpleNamespace(username="operator"), archive, RestoreOperation.Kind.DISASTER)
