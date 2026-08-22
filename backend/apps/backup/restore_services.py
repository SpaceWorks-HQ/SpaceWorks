import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup.custody import validate_deployment_custody
from apps.backup.models import BackupArchive, DeploymentRecoveryState, RestoreOperation

logger = logging.getLogger(__name__)


ALLOWED_STAGE_TRANSITIONS = {
    RestoreOperation.Stage.REQUESTED: {RestoreOperation.Stage.CLAIMED},
    RestoreOperation.Stage.CLAIMED: {RestoreOperation.Stage.PREFLIGHT},
    RestoreOperation.Stage.PREFLIGHT: {RestoreOperation.Stage.QUIESCED},
    RestoreOperation.Stage.QUIESCED: {
        RestoreOperation.Stage.DB_RESTORING,
        RestoreOperation.Stage.ABORTED,
    },
    RestoreOperation.Stage.DB_RESTORING: {
        RestoreOperation.Stage.OBJECTS_RESTORING,
        RestoreOperation.Stage.ROLLING_BACK,
    },
    RestoreOperation.Stage.OBJECTS_RESTORING: {
        RestoreOperation.Stage.VALIDATING,
        RestoreOperation.Stage.ROLLING_BACK,
    },
    RestoreOperation.Stage.VALIDATING: {
        RestoreOperation.Stage.COMPLETED,
        RestoreOperation.Stage.RESTORED_QUARANTINED,
        RestoreOperation.Stage.ROLLING_BACK,
    },
    RestoreOperation.Stage.ROLLING_BACK: {RestoreOperation.Stage.FAILED},
}


@transaction.atomic
def request_restore(actor, archive, kind):
    if archive.scope != BackupArchive.Scope.DEPLOYMENT:
        raise ValidationError("Only full-deployment archives can be restored by Phase 5A.")
    if archive.status != BackupArchive.Status.AVAILABLE:
        raise ValidationError("The selected archive is not available.")
    state = _locked_state()
    if state.mode != DeploymentRecoveryState.Mode.NORMAL:
        raise ValidationError("A restore cannot be requested while recovery is already active.")
    if RestoreOperation.objects.exclude(
        stage__in=(
            RestoreOperation.Stage.COMPLETED, RestoreOperation.Stage.RESTORED_QUARANTINED,
            RestoreOperation.Stage.FAILED, RestoreOperation.Stage.ABORTED,
        )
    ).exists():
        raise ValidationError("Another restore is already active.")
    restore = RestoreOperation.objects.create(
        archive=archive,
        kind=kind,
        requested_by=actor,
        requested_by_username_snapshot=actor.username,
    )
    audit.record(actor, "backup.restore_requested", target=restore, meta={"kind": kind})
    return restore


@transaction.atomic
def claim_restore(restore_id):
    restore = RestoreOperation.objects.select_for_update().get(pk=restore_id)
    if restore.stage != RestoreOperation.Stage.REQUESTED:
        return None
    restore.stage = RestoreOperation.Stage.CLAIMED
    restore.fencing_token = uuid.uuid4()
    restore.supervisor_heartbeat_at = timezone.now()
    restore.save()
    return restore


@transaction.atomic
def prepare_restore_resume(restore_id, error=""):
    """Rewind only stages whose table declares that no destructive effect exists."""
    restore = RestoreOperation.objects.select_for_update().get(pk=restore_id)
    if restore.stage not in {
        RestoreOperation.Stage.CLAIMED,
        RestoreOperation.Stage.PREFLIGHT,
        RestoreOperation.Stage.QUIESCED,
    }:
        return False
    if restore.stage == RestoreOperation.Stage.QUIESCED:
        restore.stage = RestoreOperation.Stage.PREFLIGHT
        restore.decision = RestoreOperation.Decision.PENDING
        restore.restore_diff = {}
        restore.decision_deadline_at = None
        state = _locked_state()
        state.mode = DeploymentRecoveryState.Mode.NORMAL
        state.active_restore = None
        state.save(update_fields=("mode", "active_restore", "updated_at"))
    restore.error_detail = str(error)[:500]
    restore.supervisor_heartbeat_at = timezone.now()
    restore.save()
    return True


@transaction.atomic
def set_stage(restore_id, stage, *, error=""):
    restore = RestoreOperation.objects.select_for_update().get(pk=restore_id)
    allowed = ALLOWED_STAGE_TRANSITIONS.get(restore.stage, set())
    if stage == RestoreOperation.Stage.FAILED and restore.stage not in {
        RestoreOperation.Stage.COMPLETED,
        RestoreOperation.Stage.RESTORED_QUARANTINED,
        RestoreOperation.Stage.ABORTED,
    }:
        allowed = {*allowed, RestoreOperation.Stage.FAILED}
    if stage not in allowed:
        raise ValidationError(
            f"Restore stage cannot move from {restore.stage} to {stage}."
        )
    returning_to_normal = (
        stage == RestoreOperation.Stage.COMPLETED
        and restore.kind == RestoreOperation.Kind.ROLLBACK_IN_PLACE
    )
    if returning_to_normal:
        # Persists every makerspace's custody state in deterministic order.
        custody = validate_deployment_custody()
        if custody.zero_recipient_off_makerspace_ids:
            # Deliberately NOT fatal -- same reasoning as the validating-stage check in
            # restore_control_records: zero recipients is an explicitly supported state
            # after a compromise, so blocking the return to normal would strand the
            # whole deployment with no repair path (quarantine exposes no recipient
            # management). Fail closed on the BUILD side, where `selection_for` already
            # refuses to encrypt to nobody -- never on recovery.
            logger.error(
                "restore_normal_with_zero_recipient_self_governed_makerspaces",
                extra={
                    "makerspace_ids": list(custody.zero_recipient_off_makerspace_ids)
                },
            )
    restore.stage = stage
    restore.supervisor_heartbeat_at = timezone.now()
    restore.error_detail = str(error)[:500]
    if stage in {RestoreOperation.Stage.COMPLETED, RestoreOperation.Stage.FAILED, RestoreOperation.Stage.ABORTED}:
        restore.completed_at = timezone.now()
    restore.save()
    if returning_to_normal:
        state = _locked_state()
        state.mode = DeploymentRecoveryState.Mode.NORMAL
        state.active_restore = None
        state.save(update_fields=("mode", "active_restore", "updated_at"))
        audit.record(
            restore.requested_by,
            "backup.restore_completed",
            target=restore,
            meta={"archive_custody_below_floor": custody.below_floor_count},
        )
    return restore


@transaction.atomic
def enter_quiescence(restore_id):
    restore = RestoreOperation.objects.select_for_update().get(pk=restore_id)
    if restore.stage != RestoreOperation.Stage.PREFLIGHT:
        raise ValidationError("Only a preflighted restore can enter quiescence.")
    restore.stage = RestoreOperation.Stage.QUIESCED
    restore.decision = RestoreOperation.Decision.PENDING
    restore.save()
    state = _locked_state()
    state.mode = DeploymentRecoveryState.Mode.QUIESCED
    state.active_restore = restore
    state.save(update_fields=("mode", "active_restore", "updated_at"))
    return restore


@transaction.atomic
def record_restore_diff(restore_id, report):
    restore = RestoreOperation.objects.select_for_update().get(pk=restore_id)
    state = _locked_state()
    if restore.stage != RestoreOperation.Stage.QUIESCED or state.mode != DeploymentRecoveryState.Mode.QUIESCED:
        raise ValidationError("Restore diff can only be recorded while writers are quiesced.")
    restore.restore_diff = report
    restore.decision_deadline_at = timezone.now() + timedelta(
        seconds=settings.BACKUP_DECISION_SECONDS
    )
    restore.save(update_fields=("restore_diff", "decision_deadline_at", "updated_at"))
    return restore


@transaction.atomic
def decide_restore(actor, restore_id, decision):
    restore = RestoreOperation.objects.select_for_update().get(pk=restore_id)
    state = _locked_state()
    now = timezone.now()
    if restore.stage != RestoreOperation.Stage.QUIESCED or state.mode != DeploymentRecoveryState.Mode.QUIESCED:
        raise ValidationError("This restore is not awaiting a decision under quiescence.")
    if not restore.decision_deadline_at or restore.decision_deadline_at <= now:
        _abort_locked(restore, state, "The bounded decision window expired.")
        audit.record(
            actor,
            "backup.restore_decision_expired",
            target=restore,
            meta={"destructive_effect": False},
        )
        return restore
    if decision not in {RestoreOperation.Decision.PROCEED, RestoreOperation.Decision.RESET, RestoreOperation.Decision.ABORT}:
        raise ValidationError({"decision": "Choose proceed, reset, or abort."})
    restore.decision = decision
    if decision == RestoreOperation.Decision.ABORT:
        _abort_locked(restore, state, "Aborted by the operator.")
    else:
        restore.save(update_fields=("decision", "updated_at"))
    audit.record(actor, "backup.restore_decided", target=restore, meta={"decision": decision})
    return restore


def _abort_locked(restore, state, reason):
    restore.decision = RestoreOperation.Decision.ABORT
    restore.stage = RestoreOperation.Stage.ABORTED
    restore.error_detail = reason
    restore.completed_at = timezone.now()
    restore.save()
    state.mode = DeploymentRecoveryState.Mode.NORMAL
    state.active_restore = None
    state.save(update_fields=("mode", "active_restore", "updated_at"))


def _locked_state():
    DeploymentRecoveryState.objects.get_or_create(pk=1)
    return DeploymentRecoveryState.objects.select_for_update().get(pk=1)
