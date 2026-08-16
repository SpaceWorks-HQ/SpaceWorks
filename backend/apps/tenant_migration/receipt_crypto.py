import base64
import hashlib
import json
import re
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
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
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return {
        "private_key": _encode(private_raw),
        "public_key": _encode(public_raw),
        "fingerprint": fingerprint_public_key(public_raw),
    }


def fingerprint_public_key(public_key):
    raw = decode_public_key(public_key) if isinstance(public_key, str) else public_key
    return hashlib.sha256(raw).hexdigest()


def decode_public_key(value):
    raw = _decode(value, "public key")
    if len(raw) != 32:
        raise ReceiptValidationError("An Ed25519 public key must be 32 bytes.")
    return raw


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
    raw = _decode(private_key, "private key")
    if len(raw) != 32:
        raise ReceiptValidationError("An Ed25519 private key must be 32 bytes.")
    signature = Ed25519PrivateKey.from_private_bytes(raw).sign(
        canonical_payload(payload)
    )
    return _encode(signature)


def verify_signature(payload, signature, public_key):
    signature_raw = _decode(signature, "signature")
    if len(signature_raw) != 64:
        raise ReceiptValidationError("An Ed25519 signature must be 64 bytes.")
    try:
        Ed25519PublicKey.from_public_bytes(decode_public_key(public_key)).verify(
            signature_raw,
            canonical_payload(payload),
        )
    except (InvalidSignature, ValueError) as exc:
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


def _encode(raw):
    return base64.b64encode(raw).decode("ascii")


def _decode(value, label):
    if not isinstance(value, str):
        raise ReceiptValidationError(f"The {label} encoding is invalid.")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ReceiptValidationError(f"The {label} encoding is invalid.") from exc
