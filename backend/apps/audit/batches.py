"""Single-writer scheduled construction and external anchoring of audit batches."""

import logging

from django.db import connection, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.audit.anchors import AnchorConflict, anchors_match, configured_sink
from apps.audit.batch_format import (
    batch_payload,
    canonical_payload_bytes,
    hashes_for_rows,
    merkle_root,
)
from apps.audit.models import (
    AuditBatch,
    AuditBatchLeaf,
    AuditLog,
    AuditMacKey,
    AuditSigningKey,
)
from apps.audit.signing import (
    AuditSigningKeyUnavailable,
    activation_envelope,
    deployment_identity,
    private_key_material,
    provision_signing_key,
    validate_genesis_database,
)
from apps.ed25519 import Ed25519Error, encode_key, sign_bytes, verify_bytes


logger = logging.getLogger(__name__)
LOCK_NAMESPACE = 734_320


class AuditBatchError(RuntimeError):
    pass


def _scope_lock(makerspace_id):
    if not connection.in_atomic_block:
        raise AuditBatchError("Audit batch locks require an atomic transaction.")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [LOCK_NAMESPACE, int(makerspace_id or 0)],
        )


def is_writable_primary():
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT NOT pg_is_in_recovery(), "
            "current_setting('transaction_read_only') = 'off'"
        )
        primary, writable = cursor.fetchone()
    return bool(primary and writable)


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
    activation = activation_envelope(signing_key)
    activation_identity = (
        activation["payload"]["deployment_id"],
        activation["payload"]["scope"],
        signing_key.fingerprint,
        0,
    )
    external = sink.fetch(activation_identity)
    if external is None or not anchors_match(external, activation):
        raise AnchorConflict("The active cutover manifest is absent or conflicting.")
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
    ):
        raise AuditBatchError("The active signing key belongs to another audit scope.")
    with transaction.atomic():
        _scope_lock(makerspace_id)
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
            signer_fingerprint=signing_key.fingerprint,
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
                private_key_material(signing_key),
            ),
            signer_fingerprint=signing_key.fingerprint,
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


def run_audit_attestation():
    # Every anchor setting is blank by default, so without this the scheduled job would
    # raise on configured_sink() every five minutes -- and the beat-less runner records a
    # swallowed failure as a successful run, which is worse than being noisy.
    from django.conf import settings as _settings

    if not getattr(_settings, "AUDIT_ATTESTATION_ANCHOR_BACKEND", ""):
        return None
    """Seal all scopes on a primary; failures are logged for scheduled retry."""
    if not is_writable_primary():
        logger.info("audit_attestation_skipped_non_writable_primary")
        return {"sealed": 0, "failed": 0, "skipped": "non_writable_primary"}
    try:
        sink = configured_sink()
    except Exception:  # noqa: BLE001 - beat retries configuration/provider recovery
        logger.exception("audit_attestation_sink_unavailable")
        return {"sealed": 0, "failed": 1}
    scope_ids = list(
        AuditMacKey.objects.order_by("makerspace_id").values_list(
            "makerspace_id", flat=True
        )
    )
    result = {"sealed": 0, "failed": 0}
    for makerspace_id in scope_ids:
        try:
            signing_key = activate_scope(makerspace_id, sink)
            synchronize_anchors(makerspace_id, sink, signing_key)
            batch = seal_scope(makerspace_id, signing_key)
            if batch is not None:
                sink.publish(batch_envelope(batch))
                result["sealed"] += 1
        except Exception:  # noqa: BLE001 - one scope/provider failure must not stop others
            result["failed"] += 1
            logger.exception(
                "audit_attestation_scope_failed",
                extra={"makerspace_id": makerspace_id},
            )
    return result
