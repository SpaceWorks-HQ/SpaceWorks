"""Canonical, verifier-gated source-partition proof for Lane E E7."""

import base64
from datetime import datetime
import hashlib
import json
import re

from django.conf import settings

from apps.backup.recipient_selection import BackupBuildError
from apps.ed25519 import (
    Ed25519Error,
    decode_key,
    fingerprint_public_key,
    verify_bytes,
)


PROOF_VERSION = "source-partition-proof-v1"
SIGNATURE_DOMAIN = b"spaceworks-b1-source-partition-proof-v1\x00"
_FORBIDDEN_LOW_ENTROPY_KEYS = frozenset({
    "raw_value", "value", "canonical_key", "canonical_bytes",
    "value_digest", "per_value_digest", "digest_by_value",
})


def verify_source_partition_proof(proof, *, expected=None):
    try:
        signature = proof["proof_signature"]
        unsigned = dict(proof)
        unsigned.pop("proof_signature")
        _validate_unsigned(unsigned)
        public = _public_key()
        if (
            signature.get("algorithm") != "ed25519"
            or signature.get("signer_fingerprint") != fingerprint_public_key(public)
            or unsigned["verifier"]["signing_key_fingerprint"]
            != fingerprint_public_key(public)
        ):
            raise ValueError
        verify_bytes(
            _signature_payload(unsigned),
            base64.b64decode(signature["value"], validate=True),
            public,
        )
        if expected:
            for key, value in expected.items():
                if unsigned.get(key) != value:
                    raise ValueError
    except (Ed25519Error, KeyError, TypeError, ValueError) as exc:
        raise BackupBuildError("The signed source-partition proof is invalid.") from exc
    return True


def proof_digest(proof):
    return hashlib.sha256(_canonical_json(proof)).hexdigest()


def _validate_unsigned(payload):
    required_header = {
        "protocol_version", "artifact_id", "capture_id",
        "source_database_identity", "source_server_identity",
        "frozen_dump_sha256", "physical_catalog_digest", "registry_digest",
        "frozen_population_ownership_digest", "readable_main_semantic_digest",
        "component_ciphertext_ledger_digest", "reservation_fence_ledger_digest",
        "user_closure_digest", "verifier", "unique_rules",
    }
    if set(payload) != required_header or payload["protocol_version"] != PROOF_VERSION:
        raise BackupBuildError("The source-partition proof header is incomplete.")
    if any(not _is_digest(payload[key]) for key in (
        "frozen_dump_sha256", "physical_catalog_digest", "registry_digest",
        "frozen_population_ownership_digest", "readable_main_semantic_digest",
        "component_ciphertext_ledger_digest", "reservation_fence_ledger_digest",
        "user_closure_digest",
    )):
        raise BackupBuildError("The source-partition proof contains an invalid digest.")
    verifier = payload["verifier"]
    if (
        set(verifier) != {
            "signing_key_fingerprint", "build", "oci_digest", "verified_at", "result"
        }
        or verifier["result"] != "pass"
        or not _is_digest(verifier["signing_key_fingerprint"])
        or not isinstance(verifier["build"], (str, dict))
        or not isinstance(verifier["oci_digest"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", verifier["oci_digest"]) is None
    ):
        raise BackupBuildError("The source verifier identity or result is invalid.")
    try:
        verified_at = datetime.fromisoformat(verifier["verified_at"])
    except (TypeError, ValueError) as exc:
        raise BackupBuildError("The source verifier time is invalid.") from exc
    if verified_at.tzinfo is None:
        raise BackupBuildError("The source verifier time must be timezone-aware.")
    identities = set()
    for rule in payload["unique_rules"]:
        required = {
            "constraint_identity", "definition_sha256", "reservation_mode",
            "qualifying_source_row_count", "qualifying_main_row_count",
            "qualifying_slice_row_count", "owning_component_count_digest",
            "component_counts", "broad_fence_definition_sha256",
            "partition_complete", "main_disjoint", "reconstruction_equal",
        }
        if set(rule) != required or _contains_forbidden(rule):
            raise BackupBuildError("A source proof unique-rule entry is malformed.")
        if (
            not _is_digest(rule["constraint_identity"])
            or not _is_digest(rule["definition_sha256"])
            or rule["reservation_mode"] not in {
                "sequence_high_water", "high_entropy_commitment", "broad_fence"
            }
            or any(
                type(rule[key]) is not int or rule[key] < 0
                for key in (
                    "qualifying_source_row_count", "qualifying_main_row_count",
                    "qualifying_slice_row_count",
                )
            )
            or rule["qualifying_source_row_count"]
            != rule["qualifying_main_row_count"] + rule["qualifying_slice_row_count"]
            or not _is_digest(rule["owning_component_count_digest"])
        ):
            raise BackupBuildError("A source proof unique-rule fact is invalid.")
        counts = rule["component_counts"]
        if (
            not isinstance(counts, list)
            or any(
                set(item) != {"component_id", "count"}
                or not isinstance(item["component_id"], str)
                or type(item["count"]) is not int
                or item["count"] < 0
                for item in counts
            )
            or len({item["component_id"] for item in counts}) != len(counts)
            or sum(item["count"] for item in counts)
            != rule["qualifying_slice_row_count"]
        ):
            raise BackupBuildError("A source proof component-count ledger is invalid.")
        if rule["constraint_identity"] in identities:
            raise BackupBuildError("A source proof repeats a unique rule.")
        identities.add(rule["constraint_identity"])
        if any(rule[key] != "pass" for key in (
            "partition_complete", "main_disjoint", "reconstruction_equal"
        )):
            raise BackupBuildError("The source proof records a non-pass rule result.")
        if rule["reservation_mode"] == "broad_fence":
            if not _is_digest(rule["broad_fence_definition_sha256"]):
                raise BackupBuildError("A low-entropy rule lacks its exact fence digest.")
        elif rule["broad_fence_definition_sha256"]:
            raise BackupBuildError("A committed rule unexpectedly carries a broad fence.")


def _contains_forbidden(value):
    if isinstance(value, dict):
        return bool(_FORBIDDEN_LOW_ENTROPY_KEYS & set(value)) or any(
            _contains_forbidden(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden(item) for item in value)
    return False


def _public_key():
    try:
        return decode_key(
            settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY, label="public key", length=32
        )
    except Ed25519Error as exc:
        raise BackupBuildError("The host archive verification identity is unavailable.") from exc


def _signature_payload(payload):
    encoded = _canonical_json(payload)
    return SIGNATURE_DOMAIN + len(encoded).to_bytes(8, "big") + encoded


def _canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _is_digest(value):
    return (
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
