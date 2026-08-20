"""Validation and canonical payload helpers for signing-key rotation."""

from apps.audit.batch_format import (
    ANCHOR_PROTOCOL_VERSION,
    FORMAT_VERSION,
    canonical_payload_bytes,
    rotation_payload,
    scope_name,
)
from apps.audit.canonical import canonical_timestamp
from apps.audit.models import AuditBatch
from apps.audit.signing import deployment_identity
from apps.ed25519 import Ed25519Error, encode_key, verify_bytes


EMPTY_HEAD_ROOT = bytes(32)


class AuditSigningKeyRotationError(RuntimeError):
    pass


def scope_head(makerspace_id):
    batch = (
        AuditBatch.objects.filter(makerspace_id=makerspace_id)
        .order_by("-batch_seq")
        .first()
    )
    if batch is None:
        return 0, EMPTY_HEAD_ROOT
    return batch.batch_seq, bytes(batch.merkle_root)


def latest_rotation_state(rotation):
    # The database transition trigger serializes and orders inserts by this identity.
    # A caller-supplied timestamp must not be able to rewrite lifecycle chronology.
    event = rotation.events.order_by("-pk").first()
    return event.state if event is not None else None


def rotation_envelope(rotation):
    return {
        "payload": rotation.payload,
        "old_signature": bytes(rotation.old_signature).hex(),
        "new_signature": bytes(rotation.new_signature).hex(),
        "old_public_key": encode_key(bytes(rotation.old_key.public_key)),
        "new_public_key": encode_key(bytes(rotation.new_key.public_key)),
    }


def rotation_audit_meta(rotation):
    return {
        "rotation_id": str(rotation.pk),
        "old_fingerprint": rotation.old_fingerprint,
        "new_fingerprint": rotation.new_fingerprint,
        "old_version": rotation.old_version,
        "new_version": rotation.new_version,
        "last_old_batch_seq": rotation.last_old_batch_seq,
        "last_old_batch_root": bytes(rotation.last_old_batch_root).hex(),
    }


def validate_rotation(rotation):
    old_key, new_key = rotation.old_key, rotation.new_key
    expected = rotation_payload(
        deployment_id=deployment_identity(),
        makerspace_id=rotation.makerspace_id,
        rotation_id=rotation.pk,
        old_key=old_key,
        new_key=new_key,
        last_old_batch_seq=rotation.last_old_batch_seq,
        last_old_batch_root=rotation.last_old_batch_root,
        created_at=rotation.created_at,
    )
    if rotation.payload != expected:
        raise AuditSigningKeyRotationError("The stored rotation payload is inconsistent.")
    if (
        rotation.old_fingerprint != old_key.fingerprint
        or rotation.new_fingerprint != new_key.fingerprint
        or rotation.old_version != old_key.version
        or rotation.new_version != new_key.version
        or new_key.version != old_key.version + 1
        or new_key.valid_from_seq != rotation.last_old_batch_seq + 1
    ):
        raise AuditSigningKeyRotationError("The rotation key binding is inconsistent.")
    try:
        payload = canonical_payload_bytes(rotation.payload)
        verify_bytes(payload, bytes(rotation.old_signature), bytes(old_key.public_key))
        verify_bytes(payload, bytes(rotation.new_signature), bytes(new_key.public_key))
    except Ed25519Error as exc:
        raise AuditSigningKeyRotationError(
            "The dual-signed rotation transition does not verify."
        ) from exc
    return rotation_envelope(rotation)


def candidate_payload(
    makerspace_id, public_key, fingerprint, version, valid_from, created_at
):
    return {
        "format_version": FORMAT_VERSION,
        "anchor_protocol_version": ANCHOR_PROTOCOL_VERSION,
        "domain": "spaceworks.audit-signing-key-generation",
        "deployment_id": deployment_identity(),
        "scope": scope_name(makerspace_id),
        "version": int(version),
        "valid_from_seq": int(valid_from),
        "public_key": encode_key(public_key),
        "signer_fingerprint": fingerprint,
        "created_at": canonical_timestamp(created_at),
    }
