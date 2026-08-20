"""Batch-chain and external-anchor phase of whole-log verification."""

import hmac

from apps.audit.anchors import AnchorError, anchors_match
from apps.audit.batch_format import scope_name
from apps.audit.batch_verification import (
    AuditFailureClass,
    AuditIntegrityFailure,
    verify_batch_local,
)
from apps.audit.batches import AuditBatchError, batch_envelope
from apps.audit.models import AuditBatch
from apps.audit.signing import deployment_identity


def _verify_batches(key, sink):
    expected_seq = 1
    previous_root = None
    batches = AuditBatch.objects.filter(makerspace_id=key.makerspace_id).order_by(
        "batch_seq"
    )
    for batch in batches:
        if batch.batch_seq != expected_seq or not _continues(batch, previous_root):
            return AuditIntegrityFailure(
                AuditFailureClass.CHAIN_CONTINUITY,
                "batch_seq or prev_batch_root does not continue the scope chain.",
                key.makerspace_id,
                batch.batch_seq,
            )
        failure = verify_batch_local(batch)
        if failure:
            return failure
        try:
            envelope = batch_envelope(batch)
        except AuditBatchError as exc:
            return AuditIntegrityFailure(
                AuditFailureClass.SIGNATURE,
                str(exc),
                key.makerspace_id,
                batch.batch_seq,
            )
        identity = (
            deployment_identity(),
            envelope["payload"]["scope"],
            key.fingerprint,
            batch.batch_seq,
        )
        try:
            external = sink.fetch(identity)
        except AnchorError as exc:
            return AuditIntegrityFailure(
                AuditFailureClass.ANCHOR_UNAVAILABLE,
                str(exc),
                key.makerspace_id,
                batch.batch_seq,
            )
        if external is None or not anchors_match(external, envelope):
            failure_class = (
                AuditFailureClass.ANCHOR_MISSING
                if external is None
                else AuditFailureClass.ANCHOR_CONFLICT
            )
            return AuditIntegrityFailure(
                failure_class,
                "The batch anchor is absent or conflicts with local state.",
                key.makerspace_id,
                batch.batch_seq,
            )
        previous_root = bytes(batch.merkle_root)
        expected_seq += 1

    # The local chain being contiguous proves nothing about its TAIL: an attacker who can
    # bypass the triggers can delete the newest batch and its leaves and leave a perfectly
    # consistent prefix. The anchor is the only witness that the batch existed, so ask it.
    scope_label = scope_name(key.makerspace_id)
    try:
        orphan = sink.fetch(
            (deployment_identity(), scope_label, key.fingerprint, expected_seq)
        )
    except AnchorError:
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_UNAVAILABLE,
            "The anchor could not be read, so the local tail cannot be trusted.",
            key.makerspace_id,
            expected_seq,
        )
    if orphan is not None:
        return AuditIntegrityFailure(
            AuditFailureClass.BATCH_MISSING,
            "An anchored batch is absent locally, so local batches were removed.",
            key.makerspace_id,
            expected_seq,
        )
    return None


def _continues(batch, previous_root):
    if previous_root is None:
        return batch.prev_batch_root is None
    return batch.prev_batch_root is not None and hmac.compare_digest(
        previous_root, bytes(batch.prev_batch_root)
    )
