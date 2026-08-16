from datetime import timedelta
import uuid

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.backup import services
from apps.backup.models import (
    BackupArchive,
    BackupLease,
    DeploymentRecoveryState,
    PlatformBackupSettings,
    RestoreOperation,
)
from apps.backup.restore_services import decide_restore, enter_quiescence, record_restore_diff, set_stage
from apps.operations.models import PeriodicTaskRun


pytestmark = pytest.mark.django_db


def restore_fixture(stage=RestoreOperation.Stage.PREFLIGHT):
    actor = User.objects.create_superuser(username=f"restore-{stage}", password="secret")
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=actor,
        status=BackupArchive.Status.AVAILABLE,
        object_key=f"backup-archives/deployment/{stage}.tar.age",
        age_encrypted=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    restore = RestoreOperation.objects.create(
        archive=archive,
        kind=RestoreOperation.Kind.ROLLBACK_IN_PLACE,
        requested_by=actor,
        stage=stage,
    )
    return actor, restore


def test_backup_has_its_own_idempotent_lease_not_a_periodic_task_claim(settings):
    settings.BACKUP_LEASE_SECONDS = 60
    first, second = uuid.uuid4(), uuid.uuid4()

    assert services._claim_lease(first) is True
    assert services._claim_lease(second) is False
    assert BackupLease.objects.get(name="deployment-backup").holder == first
    assert PeriodicTaskRun.objects.count() == 0


def test_archive_retention_comes_from_operator_settings():
    actor = User.objects.create_superuser(username="retention-super", password="secret")
    row = PlatformBackupSettings.load()
    row.retention_days = 11
    row.save(update_fields=("retention_days", "updated_at"))
    before = timezone.now()

    archive = services.create_archive(actor, scope=BackupArchive.Scope.DEPLOYMENT)

    assert before + timedelta(days=10, hours=23) < archive.expires_at
    assert archive.expires_at < before + timedelta(days=11, minutes=1)


def test_expired_operator_window_persists_an_ordinary_non_destructive_abort():
    actor, restore = restore_fixture()
    enter_quiescence(restore.pk)
    record_restore_diff(restore.pk, {"tables_compared": 200})
    RestoreOperation.objects.filter(pk=restore.pk).update(
        decision_deadline_at=timezone.now() - timedelta(seconds=1)
    )

    result = decide_restore(actor, restore.pk, RestoreOperation.Decision.PROCEED)

    result.refresh_from_db()
    state = DeploymentRecoveryState.load()
    assert result.stage == RestoreOperation.Stage.ABORTED
    assert result.decision == RestoreOperation.Decision.ABORT
    assert state.mode == DeploymentRecoveryState.Mode.NORMAL
    assert state.active_restore_id is None


def test_supervisor_stage_table_rejects_skipping_destructive_preconditions():
    _actor, restore = restore_fixture(stage=RestoreOperation.Stage.CLAIMED)
    with pytest.raises(ValidationError, match="cannot move"):
        set_stage(restore.pk, RestoreOperation.Stage.DB_RESTORING)
    with pytest.raises(ValidationError, match="preflighted"):
        enter_quiescence(restore.pk)
