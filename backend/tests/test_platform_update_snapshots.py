import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup.models import BackupArchive
from apps.updates import services
from apps.updates.errors import UpdateRefused
from apps.updates.models import PlatformUpdateSettings
from apps.updates.rollback import create_update_snapshot

pytestmark = pytest.mark.django_db
OLD = "0.5.0-main.1.aaaaaaaaaaaa"
NEW = "0.5.0-main.2.bbbbbbbbbbbb"


def archive(status="available"):
    return BackupArchive.objects.create(
        scope="deployment", object_key=f"backups/{uuid.uuid4()}.tar.age", status=status,
        expires_at=timezone.now() + timedelta(days=14),
    )


def test_snapshot_uses_the_backup_builder_boundary_and_links_only_a_completed_archive():
    services.claim_update(current_version=OLD, available_version=NEW, force=True)
    snapshot = archive()
    with patch("apps.backup.services.create_archive", return_value=snapshot) as create:
        with patch("apps.backup.services._run_archive_locked", return_value=snapshot) as build:
            created = create_update_snapshot()
    create.assert_called_once_with(None, scope=BackupArchive.Scope.DEPLOYMENT)
    build.assert_called_once_with(snapshot.pk)
    row = PlatformUpdateSettings.load()
    assert created.pk == row.pre_update_archive_id == snapshot.pk
    assert row.pre_update_version == OLD
    assert AuditLog.objects.filter(action="platform.update_snapshot_recorded", actor=None).exists()


def test_snapshot_failure_does_not_offer_an_older_updates_archive():
    row = PlatformUpdateSettings.load()
    row.pre_update_archive = archive()
    row.save()
    services.claim_update(current_version=OLD, available_version=NEW, force=True)
    failed = archive("failed")
    with patch("apps.backup.services.create_archive", return_value=failed):
        with patch("apps.backup.services._run_archive_locked", return_value=failed):
            with pytest.raises(UpdateRefused) as refusal:
                create_update_snapshot()
    assert refusal.value.detail["reason"] == "snapshot_failed"
    assert PlatformUpdateSettings.load().pre_update_archive_id is None


def test_snapshot_cannot_be_taken_without_a_claimed_update():
    with patch("apps.backup.services.create_archive") as create:
        with pytest.raises(UpdateRefused):
            create_update_snapshot()
    create.assert_not_called()


def test_recovered_or_changed_update_cannot_attach_a_late_snapshot():
    services.claim_update(current_version=OLD, available_version=NEW, force=True)
    snapshot = archive()

    def complete_during_build(_archive_id):
        services.fail_update("interrupted")
        return snapshot

    with patch("apps.backup.services.create_archive", return_value=snapshot):
        with patch("apps.backup.services._run_archive_locked", side_effect=complete_during_build):
            with pytest.raises(UpdateRefused) as refusal:
                create_update_snapshot()
    assert refusal.value.detail["reason"] == "update_changed"
    assert PlatformUpdateSettings.load().pre_update_archive_id is None
