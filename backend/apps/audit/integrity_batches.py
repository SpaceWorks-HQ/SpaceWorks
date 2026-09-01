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
from apps.audit.models import AuditBatch, AuditSigningKey
from apps.audit.signing import deployment_identity


def _verify_batches(makerspace_id, sink):
    expected_seq = 1
    previous_root = None
    keys = {
        key.fingerprint: key
        for key in AuditSigningKey.objects.filter(makerspace_id=makerspace_id)
        .exclude(rotation_to__events__state="ABORTED")
    }
    batches = AuditBatch.objects.filter(makerspace_id=makerspace_id).order_by(
        "batch_seq"
    )
    for batch in batches:
        if batch.batch_seq != expected_seq or not _continues(batch, previous_root):
            return AuditIntegrityFailure(
                AuditFailureClass.CHAIN_CONTINUITY,
                "batch_seq or prev_batch_root does not continue the scope chain.",
                makerspace_id,
                batch.batch_seq,
            )
        key = keys.get(batch.signer_fingerprint)
        if key is None:
            return AuditIntegrityFailure(
                AuditFailureClass.KEY_INTERVAL,
                "A batch names no signing-key generation in its scope.",
                makerspace_id,
                batch.batch_seq,
            )
        failure = verify_batch_local(batch, key)
        if failure:
            return failure
        try:
            envelope = batch_envelope(batch)
        except AuditBatchError as exc:
            return AuditIntegrityFailure(
                AuditFailureClass.SIGNATURE,
                str(exc),
                makerspace_id,
                batch.batch_seq,
            )
        identity = (
            deployment_identity(),
            envelope["payload"]["scope"],
            batch.signer_fingerprint,
            batch.batch_seq,
        )
        try:
            external = sink.fetch(identity)
        except AnchorError as exc:
            return AuditIntegrityFailure(
                AuditFailureClass.ANCHOR_UNAVAILABLE,
                str(exc),
                makerspace_id,
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
                makerspace_id,
                batch.batch_seq,
            )
        previous_root = bytes(batch.merkle_root)
        expected_seq += 1

    # The local chain being contiguous proves nothing about its TAIL: an attacker who can
    # bypass the triggers can delete the newest batch and its leaves and leave a perfectly
    # consistent prefix. The anchor is the only witness that the batch existed, so ask it.
    active_key = next((item for item in keys.values() if item.is_active), None)
    if active_key is None:
        return AuditIntegrityFailure(
            AuditFailureClass.KEY_INTERVAL,
            "The scope has no active signing-key interval.",
            makerspace_id,
        )
    scope_label = scope_name(makerspace_id)
    try:
        orphan = sink.fetch(
            (deployment_identity(), scope_label, active_key.fingerprint, expected_seq)
        )
    except AnchorError:
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_UNAVAILABLE,
            "The anchor could not be read, so the local tail cannot be trusted.",
            makerspace_id,
            expected_seq,
        )
    if orphan is not None:
        return AuditIntegrityFailure(
            AuditFailureClass.BATCH_MISSING,
            "An anchored batch is absent locally, so local batches were removed.",
            makerspace_id,
            expected_seq,
        )
    local_seq = expected_seq - 1
    local_root = previous_root if previous_root is not None else bytes(32)
    try:
        external_seq, external_signer, external_root = sink.fetch_scope_head(
            deployment_identity(), scope_label
        )
    except AnchorError as exc:
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_UNAVAILABLE,
            str(exc),
            makerspace_id,
            local_seq,
        )
    if (
        external_seq != local_seq
        or external_signer != active_key.fingerprint
        or not hmac.compare_digest(external_root, local_root)
    ):
        return AuditIntegrityFailure(
            AuditFailureClass.BATCH_MISSING,
            "The collector scope-global head differs from the local active chain.",
            makerspace_id,
            local_seq,
        )
    return None


def _continues(batch, previous_root):
    if previous_root is None:
        return batch.prev_batch_root is None
    return batch.prev_batch_root is not None and hmac.compare_digest(
        previous_root, bytes(batch.prev_batch_root)
    )
