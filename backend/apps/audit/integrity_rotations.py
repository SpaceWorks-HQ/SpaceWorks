"""Ordered signing-key interval and cross-key transition verification."""

import hmac

from apps.audit.anchors import AnchorError, anchors_match
from apps.audit.batch_verification import AuditFailureClass, AuditIntegrityFailure
from apps.audit.models import AuditBatch, AuditSigningKeyRotation
from apps.audit.rotations import (
    EMPTY_HEAD_ROOT,
    AuditSigningKeyRotationError,
    rotation_envelope,
    validate_rotation,
)


def _verify_rotation_chain(keys, sink):
    if not keys or keys[0].version != 1 or keys[0].valid_from_seq != 0:
        return _failure(keys, "The signing-key chain has no version-1 genesis interval.")
    active = [key for key in keys if key.is_active]
    if len(active) != 1 or active[0] != keys[-1] or active[0].valid_to_seq is not None:
        return _failure(keys, "The signing-key chain has no single open active interval.")
    if any(
        key.valid_to_seq is None or key.wrapped_private_key is not None
        for key in keys[:-1]
    ):
        return _failure(keys, "A retired interval still has an open end or live wrapped key.")
    rotations = list(
        AuditSigningKeyRotation.objects.filter(
            makerspace_id=keys[0].makerspace_id
        ).select_related("old_key", "new_key").order_by("old_version")
    )
    if len(rotations) != len(keys) - 1:
        return _failure(keys, "The signing-key generations and transitions differ.")
    for index, rotation in enumerate(rotations):
        old_key, new_key = keys[index], keys[index + 1]
        if (
            rotation.old_key_id != old_key.pk
            or rotation.new_key_id != new_key.pk
            or new_key.version != old_key.version + 1
            or old_key.valid_to_seq != rotation.last_old_batch_seq
            or new_key.valid_from_seq != rotation.last_old_batch_seq + 1
        ):
            return _failure(keys, "A transition does not join adjacent key intervals.")
        states = list(rotation.events.order_by("pk").values_list("state", flat=True))
        if states != ["PREPARED", "PUBLISHED", "FINALIZED"]:
            return _failure(keys, "A transition has no complete append-only state history.")
        expected_root = _root_at(rotation.makerspace_id, rotation.last_old_batch_seq)
        if expected_root is None or not hmac.compare_digest(
            expected_root, bytes(rotation.last_old_batch_root)
        ):
            return _failure(keys, "A transition does not bind the last old-key batch root.")
        try:
            envelope = validate_rotation(rotation)
            external = sink.fetch_rotation(sink.rotation_identity(envelope))
        except (AnchorError, AuditSigningKeyRotationError) as exc:
            return _failure(keys, f"The transition cannot be verified: {exc}")
        if external is None or not anchors_match(external, rotation_envelope(rotation)):
            return _failure(keys, "The transition anchor is absent or conflicting.")
    return None


def _root_at(makerspace_id, sequence):
    if sequence == 0:
        return EMPTY_HEAD_ROOT
    value = AuditBatch.objects.filter(
        makerspace_id=makerspace_id, batch_seq=sequence
    ).values_list("merkle_root", flat=True).first()
    return bytes(value) if value is not None else None


def _failure(keys, detail):
    return AuditIntegrityFailure(
        AuditFailureClass.ROTATION_CHAIN,
        detail,
        keys[0].makerspace_id if keys else None,
    )
