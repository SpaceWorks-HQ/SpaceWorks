"""Structured, bounded verification of a filtered slice of one makerspace's audit log.

Two phases, so the request thread never does this work and the database snapshot stays
short. ``local_phase`` runs inside one REPEATABLE READ transaction: one MAC
classification per selected row (``verify_batch=False``), ONE bulk load of every leaf of
every batch that contains a selected row, one ``verify_batch_local`` per distinct batch
from that preloaded membership, and the scope's local chain shape. ``anchor_phase`` then
re-uses the existing whole-log rules (activation, rotation chain, per-batch anchors,
deleted-tail and scope head) under the caller's scope session lock and read budget,
answering membership from the phase-one results instead of re-querying.

Coverage dimensions stay orthogonal: a MAC-valid row can be unbatched, a locally
verified batch can also be externally anchored, and nothing here sums them.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings

from apps.audit.anchors import AnchorError, configured_sink
from apps.audit.batch_verification import AuditFailureClass, verify_batch_local
from apps.audit.models import AuditBatch, AuditBatchLeaf, AuditSigningKey
from apps.audit.signing import key_authorizes_sequence
from apps.audit.verification import AuditMacStatus, classify_audit_row

from .integrity_activation import _verify_activation
from .integrity_anchor_errors import ANCHOR_TRANSPORT, VERIFICATION_UNAVAILABLE
from .integrity_batches import _continues, _verify_batches
from .integrity_rotations import _verify_rotation_chain
from .integrity_scope_anchors import verify_scope_batch_anchor

CHAIN_INVALID = {
    AuditFailureClass.CHAIN_CONTINUITY, AuditFailureClass.KEY_INTERVAL,
    AuditFailureClass.ROTATION_CHAIN, AuditFailureClass.SIGNATURE,
    AuditFailureClass.LEAF_MEMBERSHIP, AuditFailureClass.MERKLE_ROOT,
    AuditFailureClass.ACTIVATION_MISSING, AuditFailureClass.CUTOVER_MEMBERSHIP,
}
ANCHOR_INVALID = {
    AuditFailureClass.ANCHOR_MISSING, AuditFailureClass.ANCHOR_CONFLICT,
    AuditFailureClass.BATCH_MISSING,
}


@dataclass
class ScopeResult:
    counts: dict = field(default_factory=lambda: defaultdict(int))
    chain_status: str = "pending"
    anchor_status: str = "pending"
    cause: str | None = None  # internal: "anchor_transport" | "verification_unavailable"
    first_audit_log_id: int | None = None
    first_batch_seq: int | None = None
    batch_results: dict = field(default_factory=dict)  # batch pk -> failure | None
    batched_rows: dict = field(default_factory=dict)  # batch pk -> selected row count


def _note(result, audit_log_id=None, batch_seq=None):
    if result.first_audit_log_id is None and audit_log_id is not None:
        result.first_audit_log_id = audit_log_id
    if result.first_batch_seq is None and batch_seq is not None:
        result.first_batch_seq = batch_seq


def local_phase(makerspace_id, rows):
    result = ScopeResult()
    counts = result.counts
    row_batch = dict(
        AuditBatchLeaf.objects.filter(audit_log_id__in=[row.pk for row in rows])
        .values_list("audit_log_id", "batch_id")
    )
    cache = {}
    for row in rows:
        counts["row_count"] += 1
        status = classify_audit_row(row, cutover_cache=cache, verify_batch=False)
        if row.pk in row_batch and status in {AuditMacStatus.UNATTESTED, AuditMacStatus.MAC_MISSING}:
            status = AuditMacStatus.MISMATCH  # a sealed row cannot lose its MAC
        bucket = {
            AuditMacStatus.ATTESTED: "mac_valid_count",
            AuditMacStatus.UNATTESTED: "unattested_count",
            AuditMacStatus.KEY_UNAVAILABLE: "mac_unavailable_count",
        }.get(status, "mac_invalid_count")
        counts[bucket] += 1
        if bucket == "mac_invalid_count":
            _note(result, audit_log_id=row.pk)
    leaves_by_batch = defaultdict(list)
    for leaf in AuditBatchLeaf.objects.filter(
        batch_id__in=set(row_batch.values())
    ).select_related("audit_log"):
        leaves_by_batch[leaf.batch_id].append(leaf)
    batches = {batch.pk: batch for batch in AuditBatch.objects.filter(pk__in=set(row_batch.values()))}
    keys = {
        key.fingerprint: key
        for key in AuditSigningKey.objects.filter(makerspace_id=makerspace_id)
    }
    for batch_id in row_batch.values():
        result.batched_rows[batch_id] = result.batched_rows.get(batch_id, 0) + 1
    for batch_id, batch in batches.items():
        key = keys.get(batch.signer_fingerprint)
        failure = (
            "unavailable" if key is None
            else verify_batch_local(batch, key, leaves=leaves_by_batch.get(batch_id, ()))
        )
        result.batch_results[batch_id] = failure
        selected = result.batched_rows.get(batch_id, 0)
        if failure is None:
            counts["local_batch_verified_count"] += selected
        elif failure == "unavailable":
            counts["batch_unavailable_count"] += selected
        else:
            counts["batch_invalid_count"] += selected
            _note(result, batch_seq=batch.batch_seq)
    counts["unbatched_count"] += counts["row_count"] - len(row_batch)
    result.chain_status = _local_chain_status(makerspace_id, keys, result)
    return result


def _local_chain_status(makerspace_id, keys, result):
    previous_root, expected = None, 1
    for batch in AuditBatch.objects.filter(makerspace_id=makerspace_id).order_by("batch_seq").only(
        "pk", "batch_seq", "merkle_root", "prev_batch_root", "signer_fingerprint", "makerspace_id"
    ):
        key = keys.get(batch.signer_fingerprint)
        if (
            batch.batch_seq != expected
            or not _continues(batch, previous_root)
            or key is None
            or not key_authorizes_sequence(key, batch.batch_seq)
        ):
            _note(result, batch_seq=batch.batch_seq)
            return "invalid"
        previous_root, expected = bytes(batch.merkle_root), expected + 1
    return "locally_verified"


def anchor_phase(makerspace_id, result, *, read_budget, genesis_row_limit):
    """Fill anchor status; resource-limit exceptions propagate to the caller."""
    if not str(getattr(settings, "AUDIT_ATTESTATION_ANCHOR_BACKEND", "")).strip():
        result.anchor_status = "not_configured"
        return result
    try:
        sink = configured_sink(read_budget=read_budget)
    except AnchorError:
        return _unavailable(result, VERIFICATION_UNAVAILABLE)
    keys = list(
        AuditSigningKey.objects.filter(makerspace_id=makerspace_id)
        .exclude(rotation_to__events__state="ABORTED")
        .order_by("version")
    )
    if not keys:
        return _unavailable(result, VERIFICATION_UNAVAILABLE)

    def answer_from_phase_one(batch, key):
        known = result.batch_results.get(batch.pk, None)
        return None if known == "unavailable" else known

    failure = (
        _verify_activation(keys[0], sink, genesis_row_limit=genesis_row_limit)
        or _verify_rotation_chain(keys, sink)
        or _verify_batches(makerspace_id, sink, local_verifier=answer_from_phase_one,
                           anchor_verifier=verify_scope_batch_anchor)
    )
    if failure is None:
        result.anchor_status = "externally_anchored"
        result.counts["externally_anchored_count"] = result.counts["local_batch_verified_count"]
        return result
    _note(result, failure.audit_log_id, failure.batch_seq)
    if failure.failure_class in ANCHOR_INVALID:
        result.anchor_status = "invalid"
    elif failure.failure_class in CHAIN_INVALID:
        result.chain_status, result.anchor_status = "invalid", "invalid"
    else:  # ANCHOR_UNAVAILABLE or KEY_UNAVAILABLE
        return _unavailable(result, failure.cause or VERIFICATION_UNAVAILABLE)
    return result


def _unavailable(result, cause):
    result.anchor_status = "unavailable"
    result.cause = cause if cause in {ANCHOR_TRANSPORT, VERIFICATION_UNAVAILABLE} else (
        VERIFICATION_UNAVAILABLE
    )
    return result
