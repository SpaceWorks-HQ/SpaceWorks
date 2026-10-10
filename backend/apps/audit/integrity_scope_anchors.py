"""Verify fetched batch envelopes without reloading local batch membership.

Selected batches already passed local membership/signature verification in the database
phase. For every scope batch, its stored signature must verify the fetched payload and
its signed coordinates must match local state. This also checks unselected anchors
without loading unbounded, unrelated leaves or claiming their local membership coverage.
"""

from apps.audit.batch_format import (
    ANCHOR_PROTOCOL_VERSION,
    BATCH_DOMAIN,
    FORMAT_VERSION,
    canonical_payload_bytes,
    scope_name,
)
from apps.audit.batch_verification import AuditFailureClass, AuditIntegrityFailure
from apps.audit.canonical import canonical_timestamp
from apps.audit.signing import deployment_identity, key_authorizes_sequence
from apps.ed25519 import Ed25519Error, encode_key, verify_bytes


def verify_scope_batch_anchor(batch, key, external):
    expected = {
        "format_version": FORMAT_VERSION,
        "domain": BATCH_DOMAIN,
        "deployment_id": deployment_identity(),
        "scope": scope_name(batch.makerspace_id),
        "batch_seq": batch.batch_seq,
        "leaf_count": batch.leaf_count,
        "merkle_root": bytes(batch.merkle_root).hex(),
        "prev_batch_root": bytes(batch.prev_batch_root).hex() if batch.prev_batch_root is not None else None,
        "created_at": canonical_timestamp(batch.created_at),
        "signer_fingerprint": batch.signer_fingerprint,
    }
    if key.version > 1:
        expected["anchor_protocol_version"] = ANCHOR_PROTOCOL_VERSION
    try:
        payload = external["payload"]
        if (
            not isinstance(payload, dict)
            or set(payload) != {*expected, "leaves"}
            or any(payload[name] != value for name, value in expected.items())
            or not isinstance(payload["leaves"], list)
            or len(payload["leaves"]) != batch.leaf_count
            or external["signature"] != bytes(batch.signature).hex()
            or external["public_key"] != encode_key(bytes(key.public_key))
        ):
            raise ValueError("The batch anchor differs from local signed state.")
        if not key_authorizes_sequence(key, batch.batch_seq):
            return AuditIntegrityFailure(
                AuditFailureClass.KEY_INTERVAL,
                "The anchor signer is outside its authorized sequence interval.",
                batch.makerspace_id, batch.batch_seq,
            )
        verify_bytes(canonical_payload_bytes(payload), bytes(batch.signature), bytes(key.public_key))
    except (Ed25519Error, KeyError, TypeError, ValueError):
        return AuditIntegrityFailure(
            AuditFailureClass.ANCHOR_CONFLICT,
            "The fetched batch envelope does not verify against local signed state.",
            batch.makerspace_id, batch.batch_seq,
        )
    return None
