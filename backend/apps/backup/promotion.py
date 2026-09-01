"""The single no-I/O transaction that makes a Lane E artifact available."""

import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.backup.artifact_ledger import ArtifactLedgerMismatch
from apps.backup.models import (
    B1ActivationState,
    BackupArchive,
    BackupArtifactComponent,
    BackupArtifactLedger,
    BackupComponentRecipient,
    MakerspaceArchiveRecipient,
    PlatformBackupSettings,
)
from apps.backup.promotion_validation import (
    independently_recomputed_user_closure_digest,
    validate_artifact_rows,
    validate_frozen_state,
)
from apps.makerspaces.models import Makerspace


PROMOTION_LOCK_ORDER = (
    "makerspaces",
    "recipients",
    "activation",
    "artifacts",
    "components",
    "recipient_associations",
    "archive",
    "platform_settings",
)


def promote_verified_artifact(artifact_id):
    facts = BackupArtifactLedger.objects.values(
        "artifact_id", "frozen_promotion_snapshot", "predecessor_artifact_id_snapshot"
    ).get(pk=artifact_id)
    retained_ids = tuple(
        sorted(item["makerspace_id"] for item in facts["frozen_promotion_snapshot"]["retained"])
    )
    sovereign_ids = tuple(sorted(
        item["makerspace_id"]
        for item in facts["frozen_promotion_snapshot"]["retained"]
        if not item["superadmin_access_enabled"]
    ))
    artifact_ids = tuple(sorted(
        {
            facts["artifact_id"],
            *(
                (facts["predecessor_artifact_id_snapshot"],)
                if facts["predecessor_artifact_id_snapshot"] else ()
            ),
        },
        key=str,
    ))
    return _promote_atomic(artifact_id, retained_ids, sovereign_ids, artifact_ids)


@transaction.atomic
def _promote_atomic(artifact_id, retained_ids, sovereign_ids, artifact_ids):
    spaces = _lock_makerspaces(retained_ids)
    recipients = _lock_recipients(sovereign_ids)
    activations = _lock_activations(retained_ids)
    artifacts = _lock_artifacts(artifact_ids)
    artifact = artifacts.get(uuid.UUID(str(artifact_id)))
    if artifact is None:
        raise ArtifactLedgerMismatch("The durable artifact disappeared before promotion.")
    components = _lock_components(artifact)
    associations = _lock_associations(components)
    archive = BackupArchive.objects.select_for_update().get(
        pk=artifact.archive_uuid_snapshot
    )
    # Singleton, created on demand everywhere else via load(). Promotion must not
    # be the one caller that assumes some earlier code path already made the row:
    # a bare get() would abort an otherwise-valid promotion inside the
    # transaction, after all the capture work is already done.
    PlatformBackupSettings.load()
    settings_row = PlatformBackupSettings.objects.select_for_update().get(pk=1)

    if artifact.state in {
        BackupArtifactLedger.State.AVAILABLE,
        BackupArtifactLedger.State.SUPERSEDED,
        BackupArtifactLedger.State.BYTES_DELETED,
    }:
        return archive
    if artifact.state != BackupArtifactLedger.State.FINAL_VERIFIED:
        raise ArtifactLedgerMismatch("Only a stream-verified final artifact can be promoted.")
    if (
        artifact.final_verified_size_bytes != artifact.expected_size_bytes
        or artifact.final_verified_sha256 != artifact.outer_sha256
    ):
        raise ArtifactLedgerMismatch("The verified final storage facts changed.")
    _enter_promotion_state(archive)
    validate_frozen_state(
        artifact, spaces, recipients, activations, settings_row, artifacts
    )
    validate_artifact_rows(artifact, archive, components, associations)
    closure_digest = independently_recomputed_user_closure_digest(artifact)

    now = timezone.now()
    pending = []
    for makerspace_id in sovereign_ids:
        activation = activations[makerspace_id]
        if activation.state != B1ActivationState.State.OFF_PENDING:
            continue
        activation.state = B1ActivationState.State.OFF_EFFECTIVE
        activation.effective_artifact_id = artifact.artifact_id
        activation.effective_at = now
        activation.save(update_fields=(
            "state", "effective_artifact_id", "effective_at", "updated_at"
        ))
        pending.append((spaces[makerspace_id], activation))

    BackupArtifactComponent.objects.filter(artifact=artifact).update(
        storage_state=BackupArtifactComponent.StorageState.AVAILABLE,
        available_at=now,
    )
    artifact.state = BackupArtifactLedger.State.AVAILABLE
    artifact.promoted_at = now
    artifact.cleanup_pending = True
    artifact.save(update_fields=("state", "promoted_at", "cleanup_pending"))
    predecessor_id = artifact.predecessor_artifact_id_snapshot
    if predecessor_id:
        predecessor = artifacts[predecessor_id]
        if predecessor.state == BackupArtifactLedger.State.AVAILABLE:
            predecessor.state = BackupArtifactLedger.State.SUPERSEDED
            predecessor.superseded_at = now
            predecessor.save(update_fields=("state", "superseded_at"))

    archive.status = BackupArchive.Status.AVAILABLE
    archive.object_key = artifact.final_locator
    archive.manifest = artifact.outer_manifest
    archive.size_bytes = artifact.expected_size_bytes
    archive.archive_sha256 = artifact.outer_sha256
    archive.age_encrypted = True
    archive.completed_at = now
    archive.failure_detail = ""
    if archive.expires_at is None:
        archive.expires_at = now + timedelta(days=settings_row.retention_days)
    archive.save(update_fields=(
        "status", "object_key", "manifest", "size_bytes", "archive_sha256",
        "age_encrypted", "completed_at", "expires_at", "failure_detail", "updated_at",
    ))
    for makerspace, activation in pending:
        audit.record(
            archive.requested_by,
            "backup.archive_exclusion_activated",
            makerspace=makerspace,
            target=activation,
            meta={
                "artifact_id": str(artifact.artifact_id),
                "capture_id": str(artifact.capture_id),
            },
        )
    audit.record(
        archive.requested_by,
        "backup.archive_completed",
        target=archive,
        meta={
            "scope": archive.scope,
            "size_bytes": artifact.expected_size_bytes,
            "user_closure_digest": closure_digest,
        },
    )
    if archive.backup_run_id is None:
        settings_row.last_success_at = now
        settings_row.last_error = ""
        settings_row.save(
            update_fields=("last_success_at", "last_error", "updated_at")
        )
    return archive


def _enter_promotion_state(archive):
    if archive.status == BackupArchive.Status.RUNNING:
        archive.status = BackupArchive.Status.PROMOTING
        archive.save(update_fields=("status", "updated_at"))
    elif archive.status != BackupArchive.Status.PROMOTING:
        raise ArtifactLedgerMismatch("The archive is not owned for promotion.")


def _lock_makerspaces(ids):
    return {
        row.pk: row for row in Makerspace.objects.select_for_update().filter(
            pk__in=ids
        ).order_by("pk")
    }


def _lock_recipients(makerspace_ids):
    return tuple(
        MakerspaceArchiveRecipient.objects.select_for_update().filter(
            makerspace_id__in=makerspace_ids
        ).order_by("pk")
    )


def _lock_activations(makerspace_ids):
    return {
        row.makerspace_id: row
        for row in B1ActivationState.objects.select_for_update().filter(
            makerspace_id__in=makerspace_ids
        ).order_by("pk")
    }


def _lock_artifacts(artifact_ids):
    return {
        row.artifact_id: row
        for row in BackupArtifactLedger.objects.select_for_update().filter(
            artifact_id__in=artifact_ids
        ).order_by("artifact_id")
    }


def _lock_components(artifact):
    return tuple(
        BackupArtifactComponent.objects.select_for_update().filter(
            artifact=artifact
        ).order_by("pk")
    )


def _lock_associations(components):
    return tuple(
        BackupComponentRecipient.objects.select_for_update().filter(
            component_id__in=[item.pk for item in components]
        ).order_by("pk")
    )
