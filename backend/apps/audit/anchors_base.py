"""Shared envelope rules for immutable audit attestation anchors."""

from django.utils.dateparse import parse_datetime

from apps.audit.batch_format import (
    ANCHOR_PROTOCOL_VERSION,
    ROTATION_DOMAIN,
    canonical_payload_bytes,
)
from apps.ed25519 import (
    Ed25519Error,
    decode_key,
    fingerprint_public_key,
    verify_bytes,
)


class AnchorError(RuntimeError):
    pass


class AnchorConflict(AnchorError):
    pass


def _identity(payload):
    return (
        payload["deployment_id"],
        payload["scope"],
        payload["signer_fingerprint"],
        int(payload["batch_seq"]),
    )


def rotation_identity(envelope):
    payload = envelope["payload"]
    return (
        payload["deployment_id"],
        payload["scope"],
        payload["old_fingerprint"],
        payload["new_fingerprint"],
        int(payload["last_old_batch_seq"]),
    )


def _stable_envelope(envelope):
    return {key: value for key, value in envelope.items() if key != "anchored_at"}


def anchors_match(left, right):
    return _stable_envelope(left) == _stable_envelope(right)


def _validate_fetched(expected_identity, envelope):
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
        raise AnchorConflict("The anchor has an invalid envelope.")
    if _identity(envelope["payload"]) != expected_identity:
        raise AnchorConflict("The anchor identity conflicts with the requested batch.")
    anchored_at = parse_datetime(str(envelope.get("anchored_at", "")))
    if anchored_at is None or anchored_at.tzinfo is None:
        raise AnchorConflict("The anchor carries no valid freshness timestamp.")
    return envelope


def validate_rotation_envelope(envelope, expected_identity=None):
    try:
        payload = envelope["payload"]
        if (
            payload.get("anchor_protocol_version") != ANCHOR_PROTOCOL_VERSION
            or payload.get("domain") != ROTATION_DOMAIN
            or payload.get("entry_type") != "key_rotation"
        ):
            raise AnchorConflict("The rotation anchor protocol is invalid.")
        identity = rotation_identity(envelope)
        if expected_identity is not None and identity != expected_identity:
            raise AnchorConflict("The rotation anchor identity conflicts.")
        old_public = decode_key(
            envelope["old_public_key"], label="public key", length=32
        )
        new_public = decode_key(
            envelope["new_public_key"], label="public key", length=32
        )
        if (
            fingerprint_public_key(old_public) != payload["old_fingerprint"]
            or fingerprint_public_key(new_public) != payload["new_fingerprint"]
            or payload["new_public_key"] != envelope["new_public_key"]
            or int(payload["new_version"]) <= int(payload["old_version"])
            or int(payload["last_old_batch_seq"]) < 0
            or len(bytes.fromhex(payload["last_old_batch_root"])) != 32
        ):
            raise AnchorConflict("The rotation public-key binding is invalid.")
        encoded = canonical_payload_bytes(payload)
        verify_bytes(encoded, bytes.fromhex(envelope["old_signature"]), old_public)
        verify_bytes(encoded, bytes.fromhex(envelope["new_signature"]), new_public)
    except (KeyError, TypeError, ValueError, Ed25519Error) as exc:
        raise AnchorConflict("The rotation anchor is invalid.") from exc
    return identity


def _validate_fetched_rotation(expected_identity, envelope):
    validate_rotation_envelope(envelope, expected_identity)
    anchored_at = parse_datetime(str(envelope.get("anchored_at", "")))
    if anchored_at is None or anchored_at.tzinfo is None:
        raise AnchorConflict("The rotation anchor carries no valid freshness timestamp.")
    return envelope
