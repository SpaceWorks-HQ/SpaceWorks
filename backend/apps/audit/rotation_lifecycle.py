"""Transactional lifecycle operations for signing-key rotation."""

import hmac
import uuid

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.anchors import AnchorConflict, anchors_match
from apps.audit.batch_format import canonical_payload_bytes, rotation_payload
from apps.audit.models import (
    AuditSigningKey,
    AuditSigningKeyRotation,
    AuditSigningKeyRotationEvent,
)
from apps.audit.rotation_protocol import (
    AuditSigningKeyRotationError,
    candidate_payload,
    latest_rotation_state,
    rotation_audit_meta,
    scope_head,
    validate_rotation,
)
from apps.audit.signing import (
    _wrap_private_key,
    deployment_identity,
    private_key_material,
)
from apps.ed25519 import fingerprint_public_key, generate_keypair, sign_bytes


def prepare_rotation(
    makerspace_id,
    *,
    actor,
    expected_fingerprint,
    expected_head_seq,
    expected_head_root,
):
    """Create the immutable transition, durable gate, and audit row atomically."""
    from apps.audit.batches import _scope_lock

    with transaction.atomic():
        _scope_lock(makerspace_id)
        old_key = AuditSigningKey.objects.select_for_update().get(
            makerspace_id=makerspace_id, is_active=True
        )
        head_seq, head_root = scope_head(makerspace_id)
        _assert_expectations(
            old_key,
            head_seq,
            head_root,
            expected_fingerprint,
            expected_head_seq,
            expected_head_root,
        )
        if old_key.version > 1 and head_seq < old_key.valid_from_seq:
            # The interval model cannot retire a key before its first authorized
            # sequence. Reject before creating or resuming a durable pending claim.
            raise AuditSigningKeyRotationError(
                "The current signing key has not sealed an audit batch yet."
            )
        if old_key.pending_rotation_id is not None:
            rotation = AuditSigningKeyRotation.objects.select_related(
                "makerspace", "old_key", "new_key"
            ).get(pk=old_key.pending_rotation_id)
            return rotation, False
        private_key, public_key = generate_keypair()
        fingerprint = fingerprint_public_key(public_key)
        created_at = timezone.now()
        # Aborted candidates remain immutable evidence, so their version numbers are
        # intentional gaps rather than reusable generation identities.
        version = (
            AuditSigningKey.objects.filter(makerspace_id=makerspace_id)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
            + 1
        )
        activation = candidate_payload(
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
            activation_payload=activation,
            activation_signature=sign_bytes(
                canonical_payload_bytes(activation), private_key
            ),
            created_at=created_at,
        )
        rotation_id = uuid.uuid4()
        payload = rotation_payload(
            deployment_id=deployment_identity(),
            makerspace_id=makerspace_id,
            rotation_id=rotation_id,
            old_key=old_key,
            new_key=new_key,
            last_old_batch_seq=head_seq,
            last_old_batch_root=head_root,
            created_at=created_at,
        )
        encoded = canonical_payload_bytes(payload)
        rotation = AuditSigningKeyRotation.objects.create(
            id=rotation_id,
            makerspace_id=makerspace_id,
            old_key=old_key,
            new_key=new_key,
            old_fingerprint=old_key.fingerprint,
            new_fingerprint=new_key.fingerprint,
            old_version=old_key.version,
            new_version=new_key.version,
            last_old_batch_seq=head_seq,
            last_old_batch_root=head_root,
            payload=payload,
            old_signature=sign_bytes(encoded, private_key_material(old_key)),
            new_signature=sign_bytes(encoded, private_key),
            created_at=created_at,
        )
        AuditSigningKeyRotationEvent.objects.create(
            rotation=rotation,
            state=AuditSigningKeyRotationEvent.State.PREPARED,
        )
        AuditSigningKey.objects.filter(pk=old_key.pk).update(
            pending_rotation=rotation
        )
        # Atomic audit is deliberate: a recorder failure rolls back the durable gate,
        # so a retry cannot inherit a PREPARED event whose started row was lost.
        audit.record(
            actor,
            "audit.signing_key_rotation_started",
            makerspace=rotation.makerspace,
            meta=rotation_audit_meta(rotation),
        )
        return rotation, True


def publish_rotation(rotation, sink):
    """Publish and persist PUBLISHED while serialized against abort for this scope."""
    from apps.audit.batches import _scope_lock

    envelope = validate_rotation(rotation)
    identity = sink.rotation_identity(envelope)
    with transaction.atomic():
        _scope_lock(rotation.makerspace_id)
        current = AuditSigningKey.objects.select_for_update().get(pk=rotation.old_key_id)
        if current.pending_rotation_id != rotation.pk:
            raise AuditSigningKeyRotationError("The pending rotation claim changed.")
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


def finalize_rotation(rotation, sink, *, actor):
    """Activate only after publish; audit completion in the retirement transaction."""
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
        if latest_rotation_state(rotation) != AuditSigningKeyRotationEvent.State.PUBLISHED:
            raise AuditSigningKeyRotationError("The rotation has no PUBLISHED event.")
        activated_at = timezone.now()
        # Removing the live wrapped copy is not cryptographic erasure; the closed
        # sequence interval is what prevents retired-key N+1 use.
        AuditSigningKey.objects.filter(pk=old_key.pk).update(
            valid_to_seq=head_seq,
            is_active=False,
            pending_rotation=None,
            wrapped_private_key=None,
        )
        AuditSigningKey.objects.filter(pk=rotation.new_key_id).update(
            is_active=True, activated_at=activated_at
        )
        AuditSigningKeyRotationEvent.objects.create(
            rotation=rotation,
            state=AuditSigningKeyRotationEvent.State.FINALIZED,
        )
        # Atomic audit is deliberate: retirement and FINALIZED roll back together if
        # the completion record cannot be appended.
        audit.record(
            actor,
            "audit.signing_key_rotation_completed",
            makerspace=rotation.makerspace,
            meta=rotation_audit_meta(rotation),
        )
    rotation.new_key.refresh_from_db()
    return rotation.new_key


def abort_rotation(rotation, sink, *, actor, record_failure=False):
    """Abort an unanchored PREPARED rotation and reopen batch sealing atomically."""
    from apps.audit.batches import _scope_lock

    envelope = validate_rotation(rotation)
    with transaction.atomic():
        _scope_lock(rotation.makerspace_id)
        old_key = AuditSigningKey.objects.select_for_update().get(pk=rotation.old_key_id)
        state = latest_rotation_state(rotation)
        if state != AuditSigningKeyRotationEvent.State.PREPARED:
            raise AuditSigningKeyRotationError(
                "Only a PREPARED signing-key rotation can be aborted."
            )
        # This full-head check shares publish_rotation's scope lock. An exact-identity
        # lookup misses a competing transition or a batch appended outside this gate.
        payload = envelope["payload"]
        external_seq, external_fingerprint, external_root = sink.fetch_scope_head(
            payload["deployment_id"], payload["scope"]
        )
        if (
            external_seq != rotation.last_old_batch_seq
            or external_fingerprint != rotation.old_fingerprint
            or external_root is None
            or not hmac.compare_digest(
                bytes(external_root), bytes(rotation.last_old_batch_root)
            )
        ):
            raise AuditSigningKeyRotationError(
                "The external scope head diverged; the rotation must be rolled forward."
            )
        if not old_key.is_active or old_key.pending_rotation_id != rotation.pk:
            raise AuditSigningKeyRotationError("The pending rotation claim changed.")
        AuditSigningKeyRotationEvent.objects.create(
            rotation=rotation,
            state=AuditSigningKeyRotationEvent.State.ABORTED,
        )
        AuditSigningKey.objects.filter(pk=rotation.new_key_id).update(
            wrapped_private_key=None
        )
        AuditSigningKey.objects.filter(pk=old_key.pk).update(pending_rotation=None)
        meta = rotation_audit_meta(rotation)
        if record_failure:
            audit.record(
                actor,
                "audit.signing_key_rotation_failed",
                makerspace=rotation.makerspace,
                meta=meta,
            )
        audit.record(
            actor,
            "audit.signing_key_rotation_aborted",
            makerspace=rotation.makerspace,
            meta=meta,
        )
    old_key.refresh_from_db()
    return old_key


def _assert_expectations(
    key, head_seq, head_root, fingerprint, expected_seq, expected_root
):
    if key.fingerprint != fingerprint:
        raise AuditSigningKeyRotationError("The expected current fingerprint changed.")
    if head_seq != int(expected_seq):
        raise AuditSigningKeyRotationError("The expected audit batch sequence changed.")
    if not hmac.compare_digest(head_root, bytes(expected_root)):
        raise AuditSigningKeyRotationError("The expected audit batch root changed.")
