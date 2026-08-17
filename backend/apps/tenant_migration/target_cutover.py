"""Target activation and abort transitions for tenant migration."""

from django.db import transaction

from apps.accounts.models import User
from apps.audit import services as audit
from apps.makerspaces.models import Makerspace

from . import target_state
from .models_protocol import MigrationPairing, MigrationReceipt, ReceiptConsumption
from .object_import import delete_staging_objects, rollback_import_objects
from .object_verification import (
    verify_import_object_journal_state,
    verify_import_object_ownership,
    verify_import_objects,
)
from .protocol_errors import ReceiptReplayError, TransitionConflictError
from .receipts import (
    consume_once,
    issue_local_receipt,
    persisted_envelope,
    verify_and_persist_peer_receipt,
)


def activate_target(*, pairing, import_job, receipt_envelope, actor):
    """Verify objects, then atomically consume authority and activate."""
    _require_superuser(actor)
    job = _validated_target_job_unlocked(pairing, import_job)
    if not _already_activated(pairing, job):
        verify_import_objects(job)
        _require_activation_ready(job)
    result = _activate_target_transaction(
        pairing=pairing,
        import_job=import_job,
        receipt_envelope=receipt_envelope,
        actor=actor,
    )
    delete_staging_objects(job)
    return result


@transaction.atomic
def _activate_target_transaction(*, pairing, import_job, receipt_envelope, actor):
    pairing = MigrationPairing.objects.select_for_update().get(pk=pairing.pk)
    job, target = _validated_target_job(pairing, import_job)
    _require_activation_ready(job)
    receipt = verify_and_persist_peer_receipt(
        pairing,
        receipt_envelope,
        MigrationReceipt.Operation.SOURCE_CUTOVER,
    )
    consumed = ReceiptConsumption.objects.filter(receipt=receipt).first()
    if consumed is not None:
        _require_idempotent_consumption(
            consumed, ReceiptConsumption.Purpose.ACTIVATE_TARGET
        )
        if not target_state.target_has_state(target.pk, target_state.ACTIVE):
            raise TransitionConflictError(
                "The activation receipt was consumed without an active target."
            )
        return persisted_envelope(receipt)

    verify_import_object_ownership(job)
    verify_import_object_journal_state(job)
    if target_state.transition_target(
        target.pk, target_state.IMPORTING, target_state.ACTIVE
    ) != 1:
        raise TransitionConflictError(
            "Target activation requires the IMPORTING lifecycle state."
        )
    consume_once(receipt, ReceiptConsumption.Purpose.ACTIVATE_TARGET, actor)
    audit.record(
        actor,
        "tenant_migration.target_activated",
        makerspace=target,
        target=receipt,
        meta={
            "migration_id": str(receipt.migration_id),
            "receipt_id": str(receipt.receipt_id),
            "signer_fingerprint": receipt.signer_fingerprint,
            "source_deployment_id": receipt.source_deployment_id,
            "target_deployment_id": receipt.target_deployment_id,
            "format_version": receipt.format_version,
            "outcome": "active",
        },
    )
    return persisted_envelope(receipt)


def abort_target(*, pairing, import_job, actor):
    """Commit ABORTED and its receipt before deleting imported objects."""
    _require_superuser(actor)
    result = _abort_target_transaction(
        pairing=pairing, import_job=import_job, actor=actor
    )
    job = import_job.__class__.objects.select_related(
        "target_makerspace", "actor"
    ).get(pk=import_job.pk)
    rollback_import_objects(job)
    return result


@transaction.atomic
def _abort_target_transaction(*, pairing, import_job, actor):
    pairing = MigrationPairing.objects.select_for_update().get(pk=pairing.pk)
    _job, target = _validated_target_job(pairing, import_job)
    existing = MigrationReceipt.objects.filter(
        pairing=pairing,
        operation=MigrationReceipt.Operation.TARGET_ABORT,
        issued_here=True,
    ).first()
    if existing is not None:
        if not target_state.target_has_state(target.pk, target_state.ABORTED):
            raise TransitionConflictError(
                "The abort receipt exists without an aborted target."
            )
        return persisted_envelope(existing)
    if target_state.transition_target(
        target.pk, target_state.IMPORTING, target_state.ABORTED
    ) != 1:
        raise TransitionConflictError(
            "Target abort requires the IMPORTING lifecycle state."
        )
    receipt = issue_local_receipt(pairing, MigrationReceipt.Operation.TARGET_ABORT)
    audit.record(
        actor,
        "tenant_migration.target_aborted",
        makerspace=target,
        target=receipt,
        meta={
            "migration_id": str(receipt.migration_id),
            "receipt_id": str(receipt.receipt_id),
            "signer_fingerprint": receipt.signer_fingerprint,
            "source_deployment_id": receipt.source_deployment_id,
            "target_deployment_id": receipt.target_deployment_id,
            "format_version": receipt.format_version,
            "outcome": "aborted",
        },
    )
    return persisted_envelope(receipt)


def _validated_target_job(pairing, import_job):
    job = import_job.__class__.objects.select_for_update().get(pk=import_job.pk)
    _require_matching_job(pairing, job)
    target = Makerspace.objects.select_for_update().get(pk=job.target_makerspace_id)
    job.target_makerspace = target
    return job, target


def _validated_target_job_unlocked(pairing, import_job):
    job = import_job.__class__.objects.select_related("target_makerspace").get(
        pk=import_job.pk
    )
    _require_matching_job(pairing, job)
    return job


def _require_matching_job(pairing, job):
    if (
        job.pk != pairing.migration_id
        or job.target_makerspace_id is None
        or job.source_archive_digest != pairing.archive_digest
        or job.source_makerspace_id != pairing.source_tenant_id
        or job.source_deployment_id != pairing.source_deployment_id
    ):
        raise TransitionConflictError("The import job does not match the pairing.")


def _already_activated(pairing, job):
    receipt = MigrationReceipt.objects.filter(
        pairing=pairing,
        operation=MigrationReceipt.Operation.SOURCE_CUTOVER,
        consumption__purpose=ReceiptConsumption.Purpose.ACTIVATE_TARGET,
    ).first()
    return receipt is not None and target_state.target_has_state(
        job.target_makerspace_id, target_state.ACTIVE
    )


def _require_activation_ready(job):
    if (
        job.status != job.Status.COMPLETED
        or not job.verification_report
    ):
        raise TransitionConflictError(
            "Target activation requires a completed, verified import."
        )


def _require_superuser(actor):
    if not (
        getattr(actor, "is_superuser", False)
        or getattr(actor, "role", None) == User.Role.SUPERADMIN
    ):
        raise TransitionConflictError("Only a superuser can run tenant cutover.")


def _require_idempotent_consumption(consumption, expected_purpose):
    if consumption.purpose != expected_purpose:
        raise ReceiptReplayError("The receipt was consumed for a different transition.")
