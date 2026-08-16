import uuid

from django.db import IntegrityError, transaction

from apps.tenant_migration.deployment_keys import (
    deployment_signing_key,
    private_key_material,
)
from apps.tenant_migration.models_protocol import (
    MigrationPairing,
    MigrationReceipt,
    ReceiptConsumption,
)
from apps.tenant_migration.protocol_errors import (
    PairingError,
    ReceiptReplayError,
    ReceiptValidationError,
)
from apps.tenant_migration.receipt_crypto import (
    FORMAT_VERSION,
    fingerprint_public_key,
    receipt_envelope,
    receipt_payload,
    sign_payload,
    validate_payload,
    verify_signature,
)


def issue_local_receipt(pairing, operation):
    """Return the one locally issued receipt for this pairing and operation."""
    _require_atomic()
    pairing = MigrationPairing.objects.select_for_update().get(pk=pairing.pk)
    existing = MigrationReceipt.objects.filter(
        pairing=pairing,
        operation=operation,
    ).first()
    if existing is not None:
        if not existing.issued_here:
            raise ReceiptValidationError(
                "The receipt operation is already occupied by a peer receipt."
            )
        return existing

    signing_key = deployment_signing_key()
    expected = _signer_fields(pairing, operation)
    if (
        str(signing_key.deployment_id) != expected["deployment_id"]
        or signing_key.fingerprint != expected["fingerprint"]
        or signing_key.public_key != expected["public_key"]
    ):
        raise PairingError("This deployment is not the pinned signer for this receipt.")
    receipt_id = uuid.uuid4()
    payload = _payload(pairing, operation, receipt_id, signing_key.fingerprint)
    return MigrationReceipt.objects.create(
        receipt_id=receipt_id,
        pairing=pairing,
        format_version=FORMAT_VERSION,
        operation=operation,
        migration_id=pairing.migration_id,
        source_tenant_id=pairing.source_tenant_id,
        archive_digest=pairing.archive_digest,
        source_deployment_id=pairing.source_deployment_id,
        target_deployment_id=pairing.target_deployment_id,
        signer_fingerprint=signing_key.fingerprint,
        signature=sign_payload(payload, private_key_material(signing_key)),
        issued_here=True,
    )


def verify_and_persist_peer_receipt(pairing, envelope, expected_operation):
    """Verify only against pinned pairing material, then persist the exact receipt."""
    _require_atomic()
    if not isinstance(envelope, dict):
        raise ReceiptValidationError("The signed receipt envelope is invalid.")
    try:
        payload = validate_payload(envelope["payload"])
        signer_fingerprint = envelope["signer_fingerprint"]
        signature = envelope["signature"]
    except KeyError as exc:
        raise ReceiptValidationError("The signed receipt envelope is incomplete.") from exc
    if signer_fingerprint != payload["signer_fingerprint"]:
        raise ReceiptValidationError("The receipt signer names do not match.")
    expected = _signer_fields(pairing, expected_operation)
    if fingerprint_public_key(expected["public_key"]) != expected["fingerprint"]:
        raise PairingError("The pinned peer public key fingerprint is inconsistent.")
    if signer_fingerprint != expected["fingerprint"]:
        # Deliberately do not inspect envelope.get("public_key"). Receipt-supplied
        # trust material is attacker-controlled and can never satisfy pinning.
        raise ReceiptValidationError("The receipt signer is not the pinned peer.")
    _require_pairing_payload(pairing, payload, expected_operation)
    verify_signature(payload, signature, expected["public_key"])

    existing = MigrationReceipt.objects.filter(
        pairing=pairing,
        operation=expected_operation,
    ).first()
    if existing is not None:
        _require_same_receipt(existing, payload, signature)
        return existing
    try:
        with transaction.atomic():
            return MigrationReceipt.objects.create(
                receipt_id=payload["receipt_id"],
                pairing=pairing,
                format_version=payload["format_version"],
                operation=payload["operation"],
                migration_id=payload["migration_id"],
                source_tenant_id=payload["source_tenant_id"],
                archive_digest=payload["archive_digest"],
                source_deployment_id=payload["source_deployment_id"],
                target_deployment_id=payload["target_deployment_id"],
                signer_fingerprint=payload["signer_fingerprint"],
                signature=signature,
                issued_here=False,
            )
    except IntegrityError as exc:
        raise ReceiptValidationError(
            "A different receipt is already persisted for this operation."
        ) from exc


def consume_once(receipt, purpose, actor):
    """Use the receipt's one-to-one database key as the concurrency authority."""
    _require_atomic()
    try:
        with transaction.atomic():
            return ReceiptConsumption.objects.create(
                receipt=receipt,
                purpose=purpose,
                consumed_by=actor,
            )
    except IntegrityError as exc:
        raise ReceiptReplayError("The signed receipt has already been consumed.") from exc


def persisted_envelope(receipt):
    return receipt_envelope(receipt)


def _payload(pairing, operation, receipt_id, fingerprint):
    return {
        "format_version": FORMAT_VERSION,
        "operation": operation,
        "receipt_id": str(receipt_id),
        "migration_id": str(pairing.migration_id),
        "source_tenant_id": pairing.source_tenant_id,
        "archive_digest": pairing.archive_digest,
        "source_deployment_id": pairing.source_deployment_id,
        "target_deployment_id": pairing.target_deployment_id,
        "signer_fingerprint": fingerprint,
    }


def _signer_fields(pairing, operation):
    if operation == MigrationReceipt.Operation.SOURCE_CUTOVER:
        return {
            "deployment_id": pairing.source_deployment_id,
            "public_key": pairing.source_public_key,
            "fingerprint": pairing.source_fingerprint,
        }
    if operation == MigrationReceipt.Operation.TARGET_ABORT:
        return {
            "deployment_id": pairing.target_deployment_id,
            "public_key": pairing.target_public_key,
            "fingerprint": pairing.target_fingerprint,
        }
    raise ReceiptValidationError("The receipt operation is unsupported.")


def _require_pairing_payload(pairing, payload, operation):
    expected = {
        "operation": operation,
        "migration_id": str(pairing.migration_id),
        "source_tenant_id": pairing.source_tenant_id,
        "archive_digest": pairing.archive_digest,
        "source_deployment_id": pairing.source_deployment_id,
        "target_deployment_id": pairing.target_deployment_id,
    }
    if any(payload[field] != value for field, value in expected.items()):
        raise ReceiptValidationError("The receipt does not match the pinned pairing.")


def _require_same_receipt(receipt, payload, signature):
    if receipt_payload(receipt) != payload or receipt.signature != signature:
        raise ReceiptValidationError(
            "A different receipt is already persisted for this operation."
        )


def _require_atomic():
    from django.db import connection

    if not connection.in_atomic_block:
        raise RuntimeError("Receipt verification and consumption require a transaction.")
