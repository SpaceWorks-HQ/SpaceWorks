from datetime import timedelta
import uuid

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup import services
from apps.backup.models import (
    BackupArchive,
    BackupLease,
    DeploymentRecoveryState,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
    PlatformBackupSettings,
    RestoreOperation,
)
from apps.makerspaces.models import Makerspace
from apps.backup.restore_services import (
    decide_restore,
    enter_quiescence,
    record_restore_diff,
    request_restore,
    set_stage,
)
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


def test_restore_request_refuses_unsupported_format_before_side_effects():
    actor = User.objects.create_superuser(
        username="restore-wrong-format", password="secret"
    )
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=actor,
        status=BackupArchive.Status.AVAILABLE,
        object_key="backup-archives/deployment/wrong-format.tar.age",
        manifest={"format": "spaceworks-tenant-dump-v1"},
        age_encrypted=True,
        expires_at=timezone.now() + timedelta(days=1),
    )

    with pytest.raises(ValidationError, match="format_unsupported"):
        request_restore(actor, archive, RestoreOperation.Kind.ROLLBACK_IN_PLACE)

    assert not RestoreOperation.objects.exists()
    assert not DeploymentRecoveryState.objects.exists()
    assert not AuditLog.objects.filter(action="backup.restore_requested").exists()


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


def test_completed_restore_records_degraded_custody_before_normal_mode():
    actor, restore = restore_fixture(stage=RestoreOperation.Stage.VALIDATING)
    makerspace = Makerspace.objects.create(
        name="Restore degraded",
        slug="restore-degraded",
        superadmin_access_enabled=False,
    )
    MakerspaceArchiveRecipient.objects.create(
        makerspace=makerspace,
        public_recipient="age1restoredegraded",
        fingerprint="b" * 64,
        label="Only custodian",
        verified_at=timezone.now(),
    )
    state = DeploymentRecoveryState.load()
    state.mode = DeploymentRecoveryState.Mode.QUIESCED
    state.active_restore = restore
    state.save(update_fields=("mode", "active_restore", "updated_at"))

    completed = set_stage(restore.pk, RestoreOperation.Stage.COMPLETED)

    state.refresh_from_db()
    custody = MakerspaceArchiveCustodyState.objects.get(makerspace=makerspace)
    assert completed.stage == RestoreOperation.Stage.COMPLETED
    assert state.mode == DeploymentRecoveryState.Mode.NORMAL
    assert state.active_restore_id is None
    assert custody.state == custody.State.DEGRADED_ONE_RECIPIENT
    assert AuditLog.objects.filter(
        action="backup.restore_completed", actor=actor
    ).exists()


def test_completed_restore_records_but_does_not_block_zero_recipient_off_tenant():
    """Recovery must never be blocked by a tenant's custody posture.

    Zero verified recipients is an explicitly supported state -- a compromise always
    proceeds even when it breaches the floor -- so refusing to return the deployment to
    normal would strand the WHOLE deployment with no repair path, since quarantine
    exposes no recipient management. The fail-closed rule belongs on the build side,
    where `selection_for` already refuses to encrypt an archive to nobody.
    """
    _actor, restore = restore_fixture(stage=RestoreOperation.Stage.VALIDATING)
    makerspace = Makerspace.objects.create(
        name="Restore zero",
        slug="restore-zero",
        superadmin_access_enabled=False,
    )
    state = DeploymentRecoveryState.load()
    state.mode = DeploymentRecoveryState.Mode.QUIESCED
    state.active_restore = restore
    state.save(update_fields=("mode", "active_restore", "updated_at"))

    set_stage(restore.pk, RestoreOperation.Stage.COMPLETED)

    restore.refresh_from_db()
    state.refresh_from_db()
    assert restore.stage == RestoreOperation.Stage.COMPLETED
    assert state.mode == DeploymentRecoveryState.Mode.NORMAL

    # The alarm must still be raised, and durably -- proceeding is not the same as
    # ignoring. The operator has to be able to see which tenant is unprotected.
    custody = MakerspaceArchiveCustodyState.objects.get(makerspace=makerspace)
    assert custody.state == MakerspaceArchiveCustodyState.State.FLOOR_BREACHED_ZERO
