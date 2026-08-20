"""Crash-resumable Ed25519 audit signing-key rotation."""

import hmac
import uuid

from django.db import transaction
from django.utils import timezone

from apps.audit.anchors import AnchorConflict, anchors_match
from apps.audit.batch_format import (
    ANCHOR_PROTOCOL_VERSION,
    FORMAT_VERSION,
    canonical_payload_bytes,
    rotation_payload,
    scope_name,
)
from apps.audit.models import (
    AuditBatch,
    AuditSigningKey,
    AuditSigningKeyRotation,
    AuditSigningKeyRotationEvent,
)
from apps.audit.signing import (
    _wrap_private_key,
    deployment_identity,
    private_key_material,
)
from apps.audit.canonical import canonical_timestamp
from apps.ed25519 import (
    Ed25519Error,
    encode_key,
    fingerprint_public_key,
    generate_keypair,
    sign_bytes,
    verify_bytes,
)


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
    event = rotation.events.order_by("-created_at", "-pk").first()
    return event.state if event is not None else None


def rotation_envelope(rotation):
    return {
        "payload": rotation.payload,
        "old_signature": bytes(rotation.old_signature).hex(),
        "new_signature": bytes(rotation.new_signature).hex(),
        "old_public_key": encode_key(bytes(rotation.old_key.public_key)),
        "new_public_key": encode_key(bytes(rotation.new_key.public_key)),
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


def _candidate_payload(makerspace_id, public_key, fingerprint, version, valid_from, created_at):
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


def prepare_rotation(makerspace_id, *, expected_fingerprint, expected_head_seq,
                     expected_head_root):
    """Create the immutable transition and durable gate in one locked transaction."""
    from apps.audit.batches import _scope_lock

    with transaction.atomic():
        _scope_lock(makerspace_id)
        old_key = AuditSigningKey.objects.select_for_update().get(
            makerspace_id=makerspace_id, is_active=True
        )
        head_seq, head_root = scope_head(makerspace_id)
        if old_key.pending_rotation_id is not None:
            rotation = AuditSigningKeyRotation.objects.select_related(
                "old_key", "new_key"
            ).get(pk=old_key.pending_rotation_id)
            _assert_expectations(
                old_key, head_seq, head_root, expected_fingerprint,
                expected_head_seq, expected_head_root,
            )
            return rotation, False
        _assert_expectations(
            old_key, head_seq, head_root, expected_fingerprint,
            expected_head_seq, expected_head_root,
        )
        private_key, public_key = generate_keypair()
        fingerprint = fingerprint_public_key(public_key)
        created_at = timezone.now()
        version = old_key.version + 1
        candidate_payload = _candidate_payload(
            makerspace_id, public_key, fingerprint, version, head_seq + 1, created_at
        )
        new_key = AuditSigningKey.objects.create(
            makerspace_id=makerspace_id,
            wrapped_private_key=_wrap_private_key(makerspace_id, private_key),
            public_key=public_key,
            fingerprint=fingerprint,
            version=version,
            valid_from_seq=head_seq + 1,
            valid_to_seq=None,
            is_active=False,
            activation_payload=candidate_payload,
            activation_signature=sign_bytes(
                canonical_payload_bytes(candidate_payload), private_key
            ),
            created_at=created_at,
        )
        rotation_id = uuid.uuid4()
        payload = rotation_payload(
            deployment_id=deployment_identity(), makerspace_id=makerspace_id,
            rotation_id=rotation_id, old_key=old_key, new_key=new_key,
            last_old_batch_seq=head_seq, last_old_batch_root=head_root,
            created_at=created_at,
        )
        encoded = canonical_payload_bytes(payload)
        rotation = AuditSigningKeyRotation.objects.create(
            id=rotation_id, makerspace_id=makerspace_id,
            old_key=old_key, new_key=new_key,
            old_fingerprint=old_key.fingerprint, new_fingerprint=new_key.fingerprint,
            old_version=old_key.version, new_version=new_key.version,
            last_old_batch_seq=head_seq, last_old_batch_root=head_root,
            payload=payload,
            old_signature=sign_bytes(encoded, private_key_material(old_key)),
            new_signature=sign_bytes(encoded, private_key), created_at=created_at,
        )
        AuditSigningKeyRotationEvent.objects.create(
            rotation=rotation,
            state=AuditSigningKeyRotationEvent.State.PREPARED,
        )
        AuditSigningKey.objects.filter(pk=old_key.pk).update(
            pending_rotation=rotation
        )
        return rotation, True


def publish_rotation(rotation, sink):
    envelope = validate_rotation(rotation)
    identity = sink.rotation_identity(envelope)
    anchored = sink.fetch_rotation(identity)
    if anchored is None:
        anchored = sink.publish_rotation(envelope)
    if not anchors_match(anchored, envelope):
        raise AnchorConflict("The external signing-key transition conflicts.")
    AuditSigningKeyRotationEvent.objects.get_or_create(
        rotation=rotation,
        state=AuditSigningKeyRotationEvent.State.PUBLISHED,
    )
    return anchored


def finalize_rotation(rotation, sink):
    """Activate only after publish; recheck the prepared head under the scope lock."""
    from apps.audit.batches import _scope_lock

    envelope = validate_rotation(rotation)
    anchored = sink.fetch_rotation(sink.rotation_identity(envelope))
    if anchored is None or not anchors_match(anchored, envelope):
        raise AuditSigningKeyRotationError(
            "The signing-key transition is not externally anchored."
        )
    with transaction.atomic():
        _scope_lock(rotation.makerspace_id)
        old_key = AuditSigningKey.objects.select_for_update().get(
            makerspace_id=rotation.makerspace_id, is_active=True
        )
        if old_key.pk != rotation.old_key_id or old_key.pending_rotation_id != rotation.pk:
            raise AuditSigningKeyRotationError("The pending rotation claim changed.")
        head_seq, head_root = scope_head(rotation.makerspace_id)
        if head_seq != rotation.last_old_batch_seq or not hmac.compare_digest(
            head_root, bytes(rotation.last_old_batch_root)
        ):
            raise AuditSigningKeyRotationError(
                "The audit batch head changed after rotation preparation."
            )
        if not rotation.events.filter(
            state=AuditSigningKeyRotationEvent.State.PUBLISHED
        ).exists():
            raise AuditSigningKeyRotationError("The rotation has no PUBLISHED event.")
        activated_at = timezone.now()
        # This removes only the live wrapped copy. Backups/WAL may retain ciphertext;
        # sequence-interval enforcement is the protection against retired-key N+1 use.
        AuditSigningKey.objects.filter(pk=old_key.pk).update(
            valid_to_seq=head_seq, is_active=False, pending_rotation=None,
            wrapped_private_key=None,
        )
        AuditSigningKey.objects.filter(pk=rotation.new_key_id).update(
            is_active=True, activated_at=activated_at
        )
        AuditSigningKeyRotationEvent.objects.create(
            rotation=rotation,
            state=AuditSigningKeyRotationEvent.State.FINALIZED,
        )
    rotation.new_key.refresh_from_db()
    return rotation.new_key


def _assert_expectations(key, head_seq, head_root, fingerprint, expected_seq, expected_root):
    if key.fingerprint != fingerprint:
        raise AuditSigningKeyRotationError("The expected current fingerprint changed.")
    if head_seq != int(expected_seq):
        raise AuditSigningKeyRotationError("The expected audit batch sequence changed.")
    if not hmac.compare_digest(head_root, bytes(expected_root)):
        raise AuditSigningKeyRotationError("The expected audit batch root changed.")
