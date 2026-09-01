"""Small independent facts used only by the Lane E E10 acceptance sweep."""

import base64
import hashlib
import json
import struct
import uuid

from django.conf import settings
from django.utils import timezone

from apps.backup.source_partition_proof import (
    PROOF_VERSION,
    _signature_payload,
    _validate_unsigned,
)
from apps.ed25519 import decode_key, fingerprint_public_key, sign_bytes


def independent_user_closure_digest(entries, *, version=1):
    """Reproduce Decision 20 bytes without calling backup.user_closure."""

    def frame(value):
        return struct.pack(">Q", len(value)) + value

    grouped = {name: [] for name in ("included", "stubbed", "refused")}
    for disposition, source_pk, reason in entries:
        encoded = frame(str(source_pk).encode("ascii")) + frame(reason.encode())
        if encoded not in grouped[disposition]:
            grouped[disposition].append(encoded)
    payload = bytearray(b"spaceworks-user-closure-ledger\x00")
    payload.extend(struct.pack(">H", version))
    for disposition in ("included", "stubbed", "refused"):
        payload.extend(frame(disposition.encode("ascii")))
        values = sorted(grouped[disposition])
        payload.extend(struct.pack(">Q", len(values)))
        for value in values:
            payload.extend(frame(value))
    return hashlib.sha256(payload).hexdigest()


def valid_rule_proof(*, component_id=None):
    component_id = str(component_id or uuid.uuid4())
    counts = [{"component_id": component_id, "count": 1}]
    return {
        "constraint_identity": "1" * 64,
        "definition_sha256": "2" * 64,
        "reservation_mode": "broad_fence",
        "qualifying_source_row_count": 2,
        "qualifying_main_row_count": 1,
        "qualifying_slice_row_count": 1,
        "owning_component_count_digest": hashlib.sha256(json.dumps(
            counts, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
        "component_counts": counts,
        "broad_fence_definition_sha256": "3" * 64,
        "partition_complete": "pass",
        "main_disjoint": "pass",
        "reconstruction_equal": "pass",
    }


def signed_source_proof(*, artifact_id=None, capture_id=None, rules=()):
    private = decode_key(
        settings.BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY,
        label="private key",
        length=32,
    )
    public = decode_key(
        settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY,
        label="public key",
        length=32,
    )
    payload = {
        "protocol_version": PROOF_VERSION,
        "artifact_id": str(artifact_id or uuid.uuid4()),
        "capture_id": str(capture_id or uuid.uuid4()),
        "source_database_identity": "e10-source-database",
        "source_server_identity": "postgresql:16:e10",
        "frozen_dump_sha256": "4" * 64,
        "physical_catalog_digest": "5" * 64,
        "registry_digest": "6" * 64,
        "frozen_population_ownership_digest": "7" * 64,
        "readable_main_semantic_digest": "8" * 64,
        "component_ciphertext_ledger_digest": "9" * 64,
        "reservation_fence_ledger_digest": "a" * 64,
        "user_closure_digest": "b" * 64,
        "verifier": {
            "signing_key_fingerprint": fingerprint_public_key(public),
            "build": {"source_hash": "c" * 64},
            "oci_digest": "sha256:" + "d" * 64,
            "verified_at": timezone.now().isoformat(),
            "result": "pass",
        },
        "unique_rules": list(rules),
    }
    return resign_source_proof(payload)


def resign_source_proof(proof):
    unsigned = dict(proof)
    unsigned.pop("proof_signature", None)
    _validate_unsigned(unsigned)
    private = decode_key(
        settings.BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY,
        label="private key",
        length=32,
    )
    public = decode_key(
        settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY,
        label="public key",
        length=32,
    )
    return {
        **unsigned,
        "proof_signature": {
            "algorithm": "ed25519",
            "signer_fingerprint": fingerprint_public_key(public),
            "value": base64.b64encode(
                sign_bytes(_signature_payload(unsigned), private)
            ).decode("ascii"),
        },
    }
