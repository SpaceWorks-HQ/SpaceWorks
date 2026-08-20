"""Purely local verification of one audit batch's membership and signature."""

import hmac
from dataclasses import dataclass
from enum import StrEnum

from apps.audit.batch_format import (
    ANCHOR_PROTOCOL_VERSION,
    batch_payload,
    canonical_payload_bytes,
    hashes_for_rows,
    merkle_root,
)
from apps.audit.models import AuditSigningKey
from apps.audit.signing import (
    AuditSigningKeyUnavailable,
    deployment_identity,
    key_authorizes_sequence,
)
from apps.ed25519 import Ed25519Error, verify_bytes


class AuditFailureClass(StrEnum):
    ACTIVATION_MISSING = "activation_missing"
    CUTOVER_MEMBERSHIP = "cutover_membership"
    ROW_MAC_MISMATCH = "row_mac_mismatch"
    ROW_MAC_MISSING = "row_mac_missing"
    KEY_UNAVAILABLE = "key_unavailable"
    LEAF_MEMBERSHIP = "leaf_membership"
    MERKLE_ROOT = "merkle_root"
    SIGNATURE = "signature"
    CHAIN_CONTINUITY = "chain_continuity"
    ANCHOR_MISSING = "anchor_missing"
    ANCHOR_CONFLICT = "anchor_conflict"
    ANCHOR_UNAVAILABLE = "anchor_unavailable"
    # An anchored batch has no local counterpart: local batches were removed.
    BATCH_MISSING = "batch_missing"
    KEY_INTERVAL = "key_interval"
    ROTATION_CHAIN = "rotation_chain"


@dataclass(frozen=True)
class AuditIntegrityFailure:
    failure_class: AuditFailureClass
    detail: str
    makerspace_id: int | None = None
    batch_seq: int | None = None
    audit_log_id: int | None = None


def ordered_batch_rows(batch):
    leaves = list(
        batch.leaves.select_related("audit_log").order_by("leaf_position")
    )
    expected_positions = list(range(len(leaves)))
    if [leaf.leaf_position for leaf in leaves] != expected_positions:
        raise ValueError("leaf positions are not contiguous from zero")
    if len(leaves) != batch.leaf_count:
        raise ValueError("leaf_count does not match membership")
    rows = [leaf.audit_log for leaf in leaves]
    if any(row.makerspace_id != batch.makerspace_id for row in rows):
        raise ValueError("a leaf belongs to another scope")
    return rows


def verify_batch_local(batch, key=None):
    try:
        rows = ordered_batch_rows(batch)
        calculated_root = merkle_root(hashes_for_rows(rows))
    except (ValueError, TypeError) as exc:
        return AuditIntegrityFailure(
            AuditFailureClass.LEAF_MEMBERSHIP,
            str(exc),
            batch.makerspace_id,
            batch.batch_seq,
        )
    if not hmac.compare_digest(calculated_root, bytes(batch.merkle_root)):
        return AuditIntegrityFailure(
            AuditFailureClass.MERKLE_ROOT,
            "The stored root does not match the ordered leaves.",
            batch.makerspace_id,
            batch.batch_seq,
        )
    try:
        key = key or AuditSigningKey.objects.get(
            makerspace_id=batch.makerspace_id,
            fingerprint=batch.signer_fingerprint,
        )
        if not key_authorizes_sequence(key, batch.batch_seq):
            return AuditIntegrityFailure(
                AuditFailureClass.KEY_INTERVAL,
                "The signer is outside its explicit sequence interval.",
                batch.makerspace_id,
                batch.batch_seq,
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
        return AuditIntegrityFailure(
            AuditFailureClass.SIGNATURE,
            f"The batch signature does not verify: {exc}",
            batch.makerspace_id,
            batch.batch_seq,
        )
    return None
