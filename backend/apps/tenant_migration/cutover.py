from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.models_protocol import (
    MigratedOutHandoff,
    MigrationPairing,
    MigrationReceipt,
    ReceiptConsumption,
)
from apps.tenant_migration.protocol_errors import (
    ReceiptReplayError,
    TransitionConflictError,
)
from apps.tenant_migration.models_source_gate import SourceMigrationGate
from apps.tenant_migration.receipts import (
    consume_once,
    issue_local_receipt,
    persisted_envelope,
    verify_and_persist_peer_receipt,
)
from apps.tenant_migration.source_gate import (
    mark_migrated_out,
    reopen_after_verified_abort,
)


@transaction.atomic
def retire_source(*, pairing, makerspace, actor):
    """Archive source, persist MIGRATED_OUT, and issue one receipt atomically."""
    _require_superuser(actor)
    pairing = _locked_pairing(pairing)
    locked_space = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
    if str(locked_space.pk) != pairing.source_tenant_id:
        raise TransitionConflictError("The pairing names a different source tenant.")

    existing = MigratedOutHandoff.objects.filter(pairing=pairing).select_related(
        "source_cutover_receipt"
    ).first()
    if existing is not None:
        return persisted_envelope(existing.source_cutover_receipt)

    gate = SourceMigrationGate.objects.filter(makerspace=locked_space).first()
    if gate is None or gate.state != SourceMigrationGate.State.QUIESCED:
        raise TransitionConflictError(
            "Source cutover requires a quiesced source migration gate."
        )
    mark_migrated_out(
        locked_space.pk,
        gate.owner_id,
        gate.fencing_token,
        actor=actor,
    )
    lifecycle._archive_locked(locked_space, actor, archived_at=timezone.now())
    receipt = issue_local_receipt(pairing, MigrationReceipt.Operation.SOURCE_CUTOVER)
    handoff = MigratedOutHandoff.objects.create(
        source_tenant=locked_space,
        pairing=pairing,
        archive_digest=pairing.archive_digest,
        target_deployment_id=pairing.target_deployment_id,
        source_cutover_receipt=receipt,
    )
    audit.record(
        actor,
        "tenant_migration.source_migrated_out",
        makerspace=locked_space,
        target=handoff,
        meta={
            "migration_id": str(receipt.migration_id),
            "receipt_id": str(receipt.receipt_id),
            "signer_fingerprint": receipt.signer_fingerprint,
            "source_deployment_id": receipt.source_deployment_id,
            "target_deployment_id": receipt.target_deployment_id,
            "outcome": "migrated_out",
        },
    )
    return persisted_envelope(receipt)


def activate_target(*, pairing, import_job, receipt_envelope, actor):
    from .target_cutover import activate_target as activate

    return activate(
        pairing=pairing,
        import_job=import_job,
        receipt_envelope=receipt_envelope,
        actor=actor,
    )


def abort_target(*, pairing, import_job, actor):
    from .target_cutover import abort_target as abort

    return abort(pairing=pairing, import_job=import_job, actor=actor)


@transaction.atomic
def reopen_source(*, pairing, makerspace, receipt_envelope, actor):
    """Consume the target's ABORTED proof while reopening its source handoff."""
    _require_superuser(actor)
    pairing = _locked_pairing(pairing)
    locked_space = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
    if str(locked_space.pk) != pairing.source_tenant_id:
        raise TransitionConflictError("The pairing names a different source tenant.")
    receipt = verify_and_persist_peer_receipt(
        pairing,
        receipt_envelope,
        MigrationReceipt.Operation.TARGET_ABORT,
    )
    consumed = ReceiptConsumption.objects.filter(receipt=receipt).first()
    if consumed is not None:
        _require_idempotent_consumption(
            consumed,
            ReceiptConsumption.Purpose.REOPEN_SOURCE,
        )
        return persisted_envelope(receipt)

    handoff = MigratedOutHandoff.objects.select_for_update().filter(
        pairing=pairing,
        source_tenant=locked_space,
        reopened_at__isnull=True,
    ).first()
    if handoff is None or locked_space.archived_at is None:
        raise TransitionConflictError("The source has no active migrated-out handoff.")
    reopened_at = timezone.now()
    if MigratedOutHandoff.objects.filter(
        pk=handoff.pk,
        reopened_at__isnull=True,
    ).update(
        reopened_at=reopened_at,
        reopened_by=actor,
        abort_receipt=receipt,
    ) != 1:
        raise TransitionConflictError("The source handoff was already reopened.")
    if Makerspace.objects.filter(
        pk=locked_space.pk,
        archived_at__isnull=False,
    ).update(archived_at=None, archived_by=None) != 1:
        raise TransitionConflictError("The source makerspace is no longer archived.")
    reopen_after_verified_abort(locked_space, actor)
    consume_once(receipt, ReceiptConsumption.Purpose.REOPEN_SOURCE, actor)
    audit.record(
        actor,
        "tenant_migration.source_reopened",
        makerspace=locked_space,
        target=handoff,
        meta={
            "migration_id": str(receipt.migration_id),
            "receipt_id": str(receipt.receipt_id),
            "signer_fingerprint": receipt.signer_fingerprint,
            "source_deployment_id": receipt.source_deployment_id,
            "target_deployment_id": receipt.target_deployment_id,
            "outcome": "reopened",
        },
    )
    return persisted_envelope(receipt)


def has_active_migrated_out_handoff(makerspace_id):
    return MigratedOutHandoff.objects.filter(
        source_tenant_id=makerspace_id,
        state=MigratedOutHandoff.State.MIGRATED_OUT,
        reopened_at__isnull=True,
    ).exists()


def _locked_pairing(pairing):
    return MigrationPairing.objects.select_for_update().get(pk=pairing.pk)


def _require_superuser(actor):
    if not getattr(actor, "is_superuser", False):
        raise TransitionConflictError("Only a superuser can run tenant cutover.")


def _require_idempotent_consumption(consumption, expected_purpose):
    if consumption.purpose != expected_purpose:
        raise ReceiptReplayError("The receipt was consumed for a different transition.")
