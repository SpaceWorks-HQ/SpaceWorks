"""Versioned byte formats for audit leaves, Merkle trees, and signed batches."""

import hashlib
import json
import struct

from apps.audit.canonical import canonical_timestamp


FORMAT_VERSION = 1
BATCH_DOMAIN = "spaceworks.audit-batch"
CUTOVER_DOMAIN = "spaceworks.audit-cutover"
LEAF_DOMAIN = b"spaceworks.audit-batch.leaf.v1\x00"
NODE_DOMAIN = b"spaceworks.audit-batch.node.v1\x00"
GENESIS_ROW_DOMAIN = b"spaceworks.audit-cutover.row.v1\x00"


class AuditBatchFormatError(ValueError):
    pass


def scope_name(makerspace_id):
    return "global" if makerspace_id is None else f"makerspace:{int(makerspace_id)}"


def leaf_hash(*, audit_log_id, event_uuid, row_mac):
    if isinstance(audit_log_id, bool) or not 0 < int(audit_log_id) < 2**64:
        raise AuditBatchFormatError("Audit log ids must fit unsigned 64-bit encoding.")
    if event_uuid is None:
        raise AuditBatchFormatError("A batched audit row must carry an event UUID.")
    mac = bytes(row_mac) if row_mac is not None else b""
    if len(mac) != 32:
        raise AuditBatchFormatError("A batched audit row must carry a 32-byte row MAC.")
    return hashlib.sha256(
        LEAF_DOMAIN + struct.pack(">Q", int(audit_log_id)) + event_uuid.bytes + mac
    ).digest()


def merkle_root(hashes):
    level = [bytes(item) for item in hashes]
    if not level or any(len(item) != 32 for item in level):
        raise AuditBatchFormatError("A Merkle tree needs one or more 32-byte leaves.")
    while len(level) > 1:
        next_level = []
        for index in range(0, len(level), 2):
            left = level[index]
            if index + 1 == len(level):
                # Promotion preserves the tree shape. Duplicating the final node would
                # make distinct leaf sequences admit the same duplicate-last tree.
                next_level.append(left)
            else:
                next_level.append(
                    hashlib.sha256(NODE_DOMAIN + left + level[index + 1]).digest()
                )
        level = next_level
    return level[0]


def membership(rows):
    return [
        {
            "audit_log_id": int(row.pk),
            "event_uuid": str(row.event_uuid),
            "row_mac": bytes(row.row_mac).hex(),
        }
        for row in rows
    ]


def genesis_entry(row):
    # Genesis may include rows written before AUD-1's strict meta canonicalizer. JSONB
    # has already normalized object keys; Python's compact, sorted JSON encoding gives
    # those legacy values a deterministic snapshot without pretending they have a MAC.
    content = json.dumps(
        {
            "makerspace_id": row.makerspace_id,
            "event_uuid": str(row.event_uuid) if row.event_uuid is not None else None,
            "actor_id": row.actor_id,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "meta": row.meta,
            "created_at": canonical_timestamp(row.created_at),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return {
        "audit_log_id": int(row.pk),
        "event_uuid": str(row.event_uuid) if row.event_uuid is not None else None,
        "row_mac": bytes(row.row_mac).hex() if row.row_mac is not None else None,
        "content_sha256": hashlib.sha256(GENESIS_ROW_DOMAIN + content).hexdigest(),
    }


def genesis_membership(rows):
    return [genesis_entry(row) for row in rows]


def batch_payload(*, deployment_id, makerspace_id, batch_seq, rows, root,
                  prev_root, created_at, signer_fingerprint):
    return {
        "format_version": FORMAT_VERSION,
        "domain": BATCH_DOMAIN,
        "deployment_id": deployment_id,
        "scope": scope_name(makerspace_id),
        "batch_seq": int(batch_seq),
        "leaf_count": len(rows),
        "leaves": membership(rows),
        "merkle_root": bytes(root).hex(),
        "prev_batch_root": bytes(prev_root).hex() if prev_root is not None else None,
        "created_at": canonical_timestamp(created_at),
        "signer_fingerprint": signer_fingerprint,
    }


def canonical_payload_bytes(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def hashes_for_rows(rows):
    return [
        leaf_hash(
            audit_log_id=row.pk,
            event_uuid=row.event_uuid,
            row_mac=row.row_mac,
        )
        for row in rows
    ]
