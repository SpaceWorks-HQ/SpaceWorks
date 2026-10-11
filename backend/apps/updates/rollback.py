"""Update restore points reuse backup custody and restore intent, never SQL in a view."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup import restore_services
from apps.backup.models import BackupArchive, RestoreOperation
from apps.updates.models import PlatformUpdateSettings
from apps.updates.errors import UpdateRefused
from apps.updates.releases import VERSION_PATTERN

TERMINAL_STAGES = {
    RestoreOperation.Stage.COMPLETED, RestoreOperation.Stage.RESTORED_QUARANTINED,
    RestoreOperation.Stage.FAILED, RestoreOperation.Stage.ABORTED,
}


def refuse(reason, detail):
    raise UpdateRefused(reason, detail)


def active_rollback(row):
    return bool(row.rollback_restore_id and row.rollback_restore.stage not in TERMINAL_STAGES)


def snapshot_refusal(row):
    archive = row.pre_update_archive
    if archive is None:
        return "no_snapshot", "No deployment restore point was recorded for this update. A database-only backup cannot be used here."
    if not VERSION_PATTERN.fullmatch(row.pre_update_version):
        return "no_previous_version", "The previous immutable image version was not recorded."
    if archive.status != BackupArchive.Status.AVAILABLE or not archive.expires_at or archive.expires_at <= timezone.now():
        return "snapshot_unavailable", "The pre-update archive is missing, expired, or unavailable."
    if (
        archive.scope != BackupArchive.Scope.DEPLOYMENT or not archive.age_encrypted
        or not archive.archive_sha256 or not archive.completed_at
    ):
        return "snapshot_unverified", "The pre-update archive is not a completed verified deployment backup."
    manifest = archive.manifest
    if not isinstance(manifest, dict) or manifest.get("format") not in {
        "spaceworks-phase5a-v1", "spaceworks-phase5a-v2", "spaceworks-phase5a-v3",
    }:
        return "snapshot_unsupported", "The archive format is unsupported."
    # Every new deployment archive is a compound envelope, even with no sovereign
    # slices. Its outer manifest omits the legacy object ledger. Never pass one to
    # restore.sh: that would restore projected SQL and silently skip object bytes.
    if manifest.get("protocol_version") or manifest.get("partial") is not False:
        return "snapshot_unsupported", "This snapshot requires the compound restore coordinator; use the host recovery flow."
    return None


@transaction.atomic
def request_update_rollback(actor, *, archive_id, confirm_version, confirm_data_loss):
    from apps.updates.services import _locked_settings

    row = _locked_settings()
    if row.status in {PlatformUpdateSettings.Status.RUNNING, PlatformUpdateSettings.Status.QUEUED}:
        refuse("update_busy", "Wait for the update to finish or recover the interrupted update first.")
    refusal = snapshot_refusal(row)
    if refusal:
        refuse(*refusal)
    if not confirm_data_loss or confirm_version != row.pre_update_version or archive_id != row.pre_update_archive_id:
        refuse("confirmation_mismatch", "Confirm the displayed snapshot, previous version, and loss of changes since the snapshot.")
    if active_rollback(row):
        return row.rollback_restore
    if row.rollback_restore_id and row.rollback_restore.stage in {
        RestoreOperation.Stage.COMPLETED, RestoreOperation.Stage.RESTORED_QUARANTINED,
    }:
        refuse("rollback_completed", "This update's rollback has already completed.")
    try:
        restore = restore_services.request_restore(
            actor, row.pre_update_archive, RestoreOperation.Kind.ROLLBACK_IN_PLACE,
        )
    except ValidationError as exc:
        raise UpdateRefused("restore_refused", str(exc.detail)) from exc
    row.rollback_restore = restore
    row.save(update_fields=("rollback_restore", "updated_at"))
    audit.record(actor, "platform.update_rollback_requested", target=row, meta={
        "archive_id": str(row.pre_update_archive_id), "restore_id": str(restore.pk),
        "previous_version": row.pre_update_version,
    })
    return restore


def create_update_snapshot():
    """Host only, under the shared operation lock; the archive builder owns all I/O."""
    from apps.backup import services as backups
    from apps.updates.services import _locked_settings

    with transaction.atomic():
        row = _locked_settings()
        if row.status != PlatformUpdateSettings.Status.RUNNING:
            refuse("update_not_running", "A restore point can only be taken for a claimed update.")
        started = row.running_since
    archive = backups.create_archive(None, scope=BackupArchive.Scope.DEPLOYMENT)
    archive = backups._run_archive_locked(archive.pk)
    if archive is None or archive.status != BackupArchive.Status.AVAILABLE:
        refuse("snapshot_failed", "The deployment restore point failed; update cancelled.")
    with transaction.atomic():
        row = _locked_settings()
        if row.status != PlatformUpdateSettings.Status.RUNNING or row.running_since != started:
            refuse("update_changed", "The update claim changed while its restore point was being built.")
        row.pre_update_archive = archive
        row.save(update_fields=("pre_update_archive", "updated_at"))
        audit.record(None, "platform.update_snapshot_recorded", target=row, meta={
            "archive_id": str(archive.pk), "previous_version": row.pre_update_version,
        })
    return archive


def rollback_plan():
    row = PlatformUpdateSettings.load()
    if not active_rollback(row):
        return None
    refusal = snapshot_refusal(row)
    if refusal:
        refuse(*refusal)
    if row.rollback_restore.archive_id != row.pre_update_archive_id:
        refuse("snapshot_mismatch", "The rollback restore points to a different archive.")
    return row.pre_update_version, row.rollback_restore_id
