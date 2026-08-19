import json
import re
import uuid

from apps.ed25519 import (
    Ed25519Error,
    decode_key,
    encode_key,
    fingerprint_public_key as _fingerprint_public_key,
    generate_keypair,
    sign_bytes,
    verify_bytes,
)

from apps.tenant_migration.models_protocol import MigrationReceipt
from apps.tenant_migration.protocol_errors import ReceiptValidationError

FORMAT_VERSION = 1
ALGORITHM = "ed25519"
PAYLOAD_FIELDS = (
    "format_version",
    "operation",
    "receipt_id",
    "migration_id",
    "source_tenant_id",
    "archive_digest",
    "source_deployment_id",
    "target_deployment_id",
    "signer_fingerprint",
)
HEX_64 = re.compile(r"\A[0-9a-f]{64}\Z")


def generate_key_material():
    private_raw, public_raw = generate_keypair()
    return {
        "private_key": encode_key(private_raw),
        "public_key": encode_key(public_raw),
        "fingerprint": fingerprint_public_key(public_raw),
    }


def fingerprint_public_key(public_key):
    try:
        return _fingerprint_public_key(public_key)
    except Ed25519Error as exc:
        raise ReceiptValidationError(str(exc)) from exc


def decode_public_key(value):
    try:
        return decode_key(value, label="public key", length=32)
    except Ed25519Error as exc:
        raise ReceiptValidationError(str(exc)) from exc


def canonical_payload(payload):
    normalized = validate_payload(payload)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) != set(PAYLOAD_FIELDS):
        raise ReceiptValidationError("The signed receipt payload has an invalid shape.")
    normalized = {field: payload[field] for field in PAYLOAD_FIELDS}
    if normalized["format_version"] != FORMAT_VERSION:
        raise ReceiptValidationError("The signed receipt format version is unsupported.")
    if normalized["operation"] not in MigrationReceipt.Operation.values:
        raise ReceiptValidationError("The signed receipt operation is unsupported.")
    for field in ("receipt_id", "migration_id"):
        normalized[field] = _canonical_uuid(normalized[field], field)
    for field, limit in (
        ("source_tenant_id", 64),
        ("source_deployment_id", 128),
        ("target_deployment_id", 128),
    ):
        value = normalized[field]
        if not isinstance(value, str) or not value or len(value) > limit:
            raise ReceiptValidationError(f"The signed receipt {field} is invalid.")
    for field in ("archive_digest", "signer_fingerprint"):
        if not isinstance(normalized[field], str) or not HEX_64.fullmatch(
            normalized[field]
        ):
            raise ReceiptValidationError(f"The signed receipt {field} is invalid.")
    return normalized


def sign_payload(payload, private_key):
    try:
        raw = decode_key(private_key, label="private key", length=32)
        return encode_key(sign_bytes(canonical_payload(payload), raw))
    except Ed25519Error as exc:
        raise ReceiptValidationError(str(exc)) from exc


def verify_signature(payload, signature, public_key):
    try:
        verify_bytes(
            canonical_payload(payload),
            decode_key(signature, label="signature", length=64),
            decode_key(public_key, label="public key", length=32),
        )
    except Ed25519Error as exc:
        raise ReceiptValidationError("The signed receipt signature is invalid.") from exc


def receipt_payload(receipt):
    return {
        "format_version": receipt.format_version,
        "operation": receipt.operation,
        "receipt_id": str(receipt.receipt_id),
        "migration_id": str(receipt.migration_id),
        "source_tenant_id": receipt.source_tenant_id,
        "archive_digest": receipt.archive_digest,
        "source_deployment_id": receipt.source_deployment_id,
        "target_deployment_id": receipt.target_deployment_id,
        "signer_fingerprint": receipt.signer_fingerprint,
    }


def receipt_envelope(receipt):
    return {
        "payload": receipt_payload(receipt),
        "signer_fingerprint": receipt.signer_fingerprint,
        "signature": receipt.signature,
    }


def _canonical_uuid(value, field):
    if not isinstance(value, str):
        raise ReceiptValidationError(f"The signed receipt {field} is invalid.")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ReceiptValidationError(f"The signed receipt {field} is invalid.") from exc
    if str(parsed) != value:
        raise ReceiptValidationError(f"The signed receipt {field} is not canonical.")
    return value
