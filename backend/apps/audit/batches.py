"""Single-writer scheduled construction and external anchoring of audit batches."""

from django.db import connection, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.audit.anchors import AnchorConflict, anchors_match
from apps.audit.batch_format import (
    ANCHOR_PROTOCOL_VERSION,
    batch_payload,
    canonical_payload_bytes,
    hashes_for_rows,
    merkle_root,
)
from apps.audit.models import (
    AuditBatch,
    AuditBatchLeaf,
    AuditLog,
    AuditSigningKey,
)
from apps.audit.signing import (
    AuditSigningKeyUnavailable,
    activation_envelope,
    deployment_identity,
    key_authorizes_sequence,
    private_key_material,
    provision_signing_key,
    validate_genesis_database,
)
from apps.ed25519 import Ed25519Error, encode_key, sign_bytes, verify_bytes


LOCK_NAMESPACE = 734_320


class AuditBatchError(RuntimeError):
    pass


class AuditSigningKeyRotationPending(AuditBatchError):
    """A durable rotation claim pauses only batch sealing, not audit writes."""


def _scope_lock(makerspace_id):
    if not connection.in_atomic_block:
        raise AuditBatchError("Audit batch locks require an atomic transaction.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [LOCK_NAMESPACE, int(makerspace_id or 0)],
        )


def _ordered_rows(batch):
    leaves = batch.leaves.select_related("audit_log").order_by("leaf_position")
    return [leaf.audit_log for leaf in leaves]


def batch_envelope(batch):
    try:
        rows = _ordered_rows(batch)
        key = AuditSigningKey.objects.get(
            makerspace_id=batch.makerspace_id,
            fingerprint=batch.signer_fingerprint,
        )
        payload = batch_payload(
            deployment_id=deployment_identity(),
            makerspace_id=batch.makerspace_id,
            batch_seq=batch.batch_seq,
            rows=rows,
            root=batch.merkle_root,
            prev_root=batch.prev_batch_root,
            created_at=batch.created_at,
            signer_fingerprint=batch.signer_fingerprint,
            anchor_protocol_version=(
                ANCHOR_PROTOCOL_VERSION if key.version > 1 else None
            ),
        )
        if not key_authorizes_sequence(key, batch.batch_seq):
            raise AuditBatchError(
                "The batch signer is outside its authorized sequence interval."
            )
        verify_bytes(
            canonical_payload_bytes(payload),
            bytes(batch.signature),
            bytes(key.public_key),
        )
    except (
        AuditSigningKey.DoesNotExist,
        AuditSigningKeyUnavailable,
        Ed25519Error,
        ValueError,
    ) as exc:
        raise AuditBatchError("A local audit batch signature does not verify.") from exc
    return {
        "payload": payload,
        "signature": bytes(batch.signature).hex(),
        "public_key": encode_key(bytes(key.public_key)),
    }


def activate_scope(makerspace_id, sink):
    key, _created = provision_signing_key(makerspace_id)
    if key.version > 1:
        if key.activated_at is None or not key.is_active:
            raise AuditBatchError("The rotated signing key is not active.")
        return key
    validate_genesis_database(key)
    envelope = activation_envelope(key)
    try:
        verify_bytes(
            canonical_payload_bytes(key.activation_payload),
            bytes(key.activation_signature),
            bytes(key.public_key),
        )
    except Ed25519Error as exc:
        raise AuditBatchError("The local activation manifest does not verify.") from exc
    identity = (
        envelope["payload"]["deployment_id"],
        envelope["payload"]["scope"],
        envelope["payload"]["signer_fingerprint"],
        0,
    )
    anchored = sink.fetch(identity)
    if anchored is None:
        anchored = sink.publish(envelope)
    if not anchors_match(anchored, envelope):
        raise AnchorConflict("The external cutover manifest conflicts with this scope.")
    if key.activated_at is None:
        AuditSigningKey.objects.filter(pk=key.pk, activated_at=None).update(
            activated_at=timezone.now()
        )
        key.refresh_from_db(fields=["activated_at"])
    return key


def synchronize_anchors(makerspace_id, sink, signing_key):
    genesis_key = AuditSigningKey.objects.get(
        makerspace_id=makerspace_id, version=1
    )
    activation = activation_envelope(genesis_key)
    activation_identity = (
        activation["payload"]["deployment_id"],
        activation["payload"]["scope"],
        genesis_key.fingerprint,
        0,
    )
    external = sink.fetch(activation_identity)
    if external is None or not anchors_match(external, activation):
        raise AnchorConflict("The active cutover manifest is absent or conflicting.")
    from apps.audit.models import AuditSigningKeyRotation
    from apps.audit.rotations import rotation_envelope, validate_rotation

    for rotation in AuditSigningKeyRotation.objects.filter(
        makerspace_id=makerspace_id,
        events__state="FINALIZED",
    ).select_related("old_key", "new_key").distinct().order_by("old_version"):
        envelope = validate_rotation(rotation)
        identity = sink.rotation_identity(envelope)
        anchored = sink.fetch_rotation(identity)
        if anchored is None or not anchors_match(anchored, rotation_envelope(rotation)):
            raise AnchorConflict("A finalized signing-key transition is absent or conflicting.")
    for batch in AuditBatch.objects.filter(makerspace_id=makerspace_id).order_by(
        "batch_seq"
    ):
        envelope = batch_envelope(batch)
        identity = (
            envelope["payload"]["deployment_id"],
            envelope["payload"]["scope"],
            envelope["payload"]["signer_fingerprint"],
            batch.batch_seq,
        )
        anchored = sink.fetch(identity)
        if anchored is None:
            sink.publish(envelope)
        elif not anchors_match(anchored, envelope):
            raise AnchorConflict(
                f"External anchor conflicts at batch_seq={batch.batch_seq}."
            )


def seal_scope(makerspace_id, signing_key):
    """Atomically claim the exact visible set of MAC-bearing unbatched rows."""
    if (
        signing_key.makerspace_id != makerspace_id
        or signing_key.activated_at is None
        or not signing_key.is_active
    ):
        raise AuditBatchError("The active signing key belongs to another audit scope.")
    with transaction.atomic():
        _scope_lock(makerspace_id)
        active_key = AuditSigningKey.objects.select_for_update().get(
            makerspace_id=makerspace_id, is_active=True
        )
        if active_key.pk != signing_key.pk:
            raise AuditBatchError("The supplied signing key is no longer active.")
        if active_key.pending_rotation_id is not None:
            raise AuditSigningKeyRotationPending(
                "Audit batch sealing is paused by a pending signing-key rotation."
            )
        previous = (
            AuditBatch.objects.filter(makerspace_id=makerspace_id)
            .order_by("-batch_seq")
            .first()
        )
        already_batched = AuditBatchLeaf.objects.filter(audit_log_id=OuterRef("pk"))
        rows = list(
            AuditLog.objects.filter(
                makerspace_id=makerspace_id,
                row_mac__isnull=False,
                event_uuid__isnull=False,
            )
            .annotate(_is_batched=Exists(already_batched))
            .filter(_is_batched=False)
            .order_by("pk")
        )
        if not rows:
            return None
        hashes = hashes_for_rows(rows)
        root = merkle_root(hashes)
        batch_seq = previous.batch_seq + 1 if previous else 1
        if not key_authorizes_sequence(active_key, batch_seq):
            raise AuditBatchError(
                "The active signing key does not authorize the next batch sequence."
            )
        prev_root = bytes(previous.merkle_root) if previous else None
        created_at = timezone.now()
        payload = batch_payload(
            deployment_id=deployment_identity(),
            makerspace_id=makerspace_id,
            batch_seq=batch_seq,
            rows=rows,
            root=root,
            prev_root=prev_root,
            created_at=created_at,
            signer_fingerprint=active_key.fingerprint,
            anchor_protocol_version=(
                ANCHOR_PROTOCOL_VERSION if active_key.version > 1 else None
            ),
        )
        batch = AuditBatch.objects.create(
            makerspace_id=makerspace_id,
            batch_seq=batch_seq,
            leaf_count=len(rows),
            merkle_root=root,
            prev_batch_root=prev_root,
            created_at=created_at,
            signature=sign_bytes(
                canonical_payload_bytes(payload),
                private_key_material(active_key),
            ),
            signer_fingerprint=active_key.fingerprint,
        )
        AuditBatchLeaf.objects.bulk_create(
            [
                AuditBatchLeaf(
                    batch=batch,
                    audit_log_id=row.pk,
                    leaf_position=position,
                )
                for position, row in enumerate(rows)
            ]
        )
        return batch


from .batch_scheduler import is_writable_primary, run_audit_attestation  # noqa: E402,F401
