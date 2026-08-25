"""Persist supervisor facts outside a database that is about to be replaced."""

import json
from datetime import timedelta
from pathlib import Path

import logging

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from apps.backup import storage
from apps.backup.models import (
    BackupArchive,
    DeploymentRecoveryState,
    PlatformBackupSettings,
    RestoreOperation,
)

logger = logging.getLogger(__name__)


def export_control_record(restore_id, output, decision=None):
    restore = RestoreOperation.objects.get(pk=restore_id)
    payload = {
        "decision": decision or restore.decision,
        "restore_diff": restore.restore_diff,
        "decision_deadline_at": (
            restore.decision_deadline_at.isoformat()
            if restore.decision_deadline_at else None
        ),
        "fencing_token": str(restore.fencing_token or ""),
        "requested_by_username": restore.requested_by_username_snapshot,
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


@transaction.atomic
def rehydrate_control_record(restore_id, options):
    from apps.accounts.models import User

    control = json.loads(Path(options["control_record"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
    completed_at = timezone.now()
    archive = BackupArchive.objects.select_for_update().get(
        pk=options["archive_id"]
    )
    archive.status = BackupArchive.Status.AVAILABLE
    archive.manifest = manifest
    archive.age_encrypted = True
    archive.completed_at = completed_at
    archive.failure_detail = ""
    if archive.expires_at is None:
        archive.expires_at = completed_at + timedelta(
            days=PlatformBackupSettings.load().retention_days
        )
    archive.save(
        update_fields=(
            "status",
            "manifest",
            "age_encrypted",
            "completed_at",
            "failure_detail",
            "expires_at",
            "updated_at",
        )
    )
    transaction.on_commit(
        lambda: storage.delete_archive_prefix(
            f"backup-archives/staging/{archive.pk}/"
        )
    )
    requested_by = User.objects.filter(
        username=control.get("requested_by_username", "")
    ).first()
    restore, _ = RestoreOperation.objects.update_or_create(
        pk=restore_id,
        defaults={
            "archive_id": options["archive_id"],
            "kind": options["kind"],
            "requested_by": requested_by,
            "requested_by_username_snapshot": control.get("requested_by_username", ""),
            "stage": RestoreOperation.Stage.DB_RESTORING,
            "decision": control["decision"],
            "restore_diff": control.get("restore_diff") or {},
            "decision_deadline_at": control.get("decision_deadline_at"),
            "fencing_token": control.get("fencing_token") or None,
        },
    )
    state = DeploymentRecoveryState.load()
    state.mode = DeploymentRecoveryState.Mode.QUIESCED
    state.active_restore = restore
    state.save(update_fields=("mode", "active_restore", "updated_at"))
    return restore


def validate_restored_state(restore_id):
    restore = RestoreOperation.objects.get(pk=restore_id)
    if restore.stage != RestoreOperation.Stage.VALIDATING:
        raise RuntimeError("Only the validating stage can run restored-state checks.")
    call_command("check", verbosity=0)
    from apps.accounts.token_guard import validate_token_configuration
    from apps.backup.custody import validate_deployment_custody
    from apps.backup.route_guard import validate_recovery_route_allowlists
    from apps.encryption.readiness import assert_ready

    assert_ready()
    # `validate_deployment_custody` has already PERSISTED each makerspace's custody
    # state in deterministic order, so the alarm exists before we decide anything.
    custody = validate_deployment_custody()
    if custody.zero_recipient_off_makerspace_ids:
        # Deliberately NOT fatal. Zero recipients is an explicitly supported state --
        # a compromise always proceeds even when it breaches the floor -- so aborting
        # here would make every deployment archive containing such a tenant
        # unrestorable, with no repair path (quarantine blocks acknowledgement and
        # exposes no recipient management). Refusing the restore does not fix the
        # tenant's custody posture; it only prevents recovery.
        # The fail-closed rule belongs on the BUILD side, where `selection_for`
        # already refuses to encrypt an archive to nobody.
        logger.error(
            "restore_zero_recipient_self_governed_makerspaces",
            extra={"makerspace_ids": list(custody.zero_recipient_off_makerspace_ids)},
        )
    validate_token_configuration()
    validate_recovery_route_allowlists()
