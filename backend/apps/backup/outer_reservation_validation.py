"""Fail-closed structural and signed binding checks for E7 outer facts."""

import base64
import hashlib
import json

from apps.backup.recipient_selection import BackupBuildError
from apps.backup.postgres_client import server_major
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.reservation_registry import (
    canonicalizer_identity,
    component_canonicalizer_identities,
)
from apps.backup.source_partition_proof import verify_source_partition_proof


_ORACLE_NAMES = frozenset({
    "raw_value", "value", "canonical_key", "canonical_bytes",
    "value_digest", "per_value_digest", "digest_by_value",
})


def validate_reservation_manifest(manifest, component_ledger):
    try:
        salt = base64.b64decode(manifest["reservation_salt"], validate=True)
        if len(salt) != 32 or not _digest(manifest["reservation_registry_digest"]):
            raise ValueError
        slice_ids = {
            item["component_id"] for item in manifest["slice_components"]
        }
        commitments = manifest["reservation_commitments"]
        broad = manifest["broad_fence_scopes"]
        relationships = manifest["relationship_fence_scopes"]
        objects = manifest["object_namespace_fences"]
        sequences = manifest["sequence_reservations"]
        _validate_commitments(commitments, slice_ids)
        for facts, kind in (
            (broad, "broad"),
            (relationships, "relationship"),
            (objects, "object"),
        ):
            _validate_fences(facts, slice_ids, kind)
        _validate_sequences(sequences)
        ledger = {
            "reservation_salt": manifest["reservation_salt"],
            "reservation_registry_digest": manifest["reservation_registry_digest"],
            "reservation_commitments": commitments,
            "broad_fence_scopes": broad,
            "relationship_fence_scopes": relationships,
            "object_namespace_fences": objects,
            "sequence_reservations": sequences,
        }
        expected = {
            "artifact_id": manifest["artifact_id"],
            "capture_id": manifest["capture_id"],
            "physical_catalog_digest": manifest["main_component"][
                "schema_catalog_digest"
            ],
            "registry_digest": manifest["reservation_registry_digest"],
            "readable_main_semantic_digest": manifest["main_component"][
                "semantic_digest"
            ],
            "component_ciphertext_ledger_digest": _json_digest(component_ledger),
            "reservation_fence_ledger_digest": _json_digest(ledger),
            "user_closure_digest": manifest["user_closure_digest"],
        }
        proof = manifest["source_partition_proof"]
        verify_source_partition_proof(proof, expected=expected)
        _bind_rules(proof["unique_rules"], commitments, broad, sequences, slice_ids)
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupBuildError(
            "The outer manifest reservation/proof binding is invalid."
        ) from exc


def _validate_commitments(facts, slice_ids):
    rules = {item.identity: item for item in load_unique_rules()}
    postgres_major = server_major()
    seen = set()
    required = {
        "constraint_identity", "definition_sha256", "canonicalizer_identity",
        "key_component_identities", "component_commitments",
    }
    for item in facts:
        if set(item) != required:
            raise ValueError
        if any(not _digest(item[key]) for key in (
            "constraint_identity", "definition_sha256", "canonicalizer_identity",
        )):
            raise ValueError
        components = item["key_component_identities"]
        if not components or any(
            set(component) != {"type_identity", "canonicalizer_identity"}
            or not component["type_identity"]
            or not component["canonicalizer_identity"]
            for component in components
        ):
            raise ValueError
        groups = item["component_commitments"]
        if (
            not groups
            or {group["component_id"] for group in groups} != slice_ids
            or any(
                set(group) != {"component_id", "commitments"}
                or group["commitments"] != sorted(set(group["commitments"]))
                or any(not _digest(value) for value in group["commitments"])
                for group in groups
            )
        ):
            raise ValueError
        identity = item["constraint_identity"]
        if identity in seen:
            raise ValueError
        rule = rules.get(identity)
        if (
            rule is None
            or rule.definition_sha256 != item["definition_sha256"]
            or canonicalizer_identity(rule, postgres_major)
            != item["canonicalizer_identity"]
            or list(component_canonicalizer_identities(rule, postgres_major))
            != item["key_component_identities"]
        ):
            raise ValueError
        seen.add(identity)


def _validate_fences(facts, slice_ids, kind):
    seen = set()
    for item in facts:
        if not isinstance(item, dict) or _contains_oracle(item):
            raise ValueError
        required = {
            "definition_sha256", "component_ids", "schema", "table", "operations"
        }
        if not required <= set(item) or not _digest(item["definition_sha256"]):
            raise ValueError
        if (
            item["component_ids"] != sorted(set(item["component_ids"]))
            or not set(item["component_ids"]) <= slice_ids
            or not item["component_ids"]
        ):
            raise ValueError
        allowed = {"insert", "update"}
        if kind != "broad":
            allowed |= {"delete", "overwrite"}
        if not set(item["operations"]) <= allowed:
            raise ValueError
        if item["definition_sha256"] in seen:
            raise ValueError
        seen.add(item["definition_sha256"])


def _validate_sequences(facts):
    seen = set()
    for item in facts:
        required = {
            "schema", "sequence", "table", "column", "type_identity", "increment",
            "start", "minimum", "maximum", "cycle", "cache", "captured_last_value",
            "captured_is_called", "installed_last_value", "installed_is_called",
            "next_generated_value", "constraint_identity", "definition_sha256",
        }
        if set(item) != required:
            raise ValueError
        identifiers = ("schema", "sequence", "table", "column", "type_identity")
        numeric = (
            "increment", "start", "minimum", "maximum", "cache",
            "captured_last_value", "installed_last_value", "next_generated_value",
        )
        if (
            any(not isinstance(item[key], str) or not item[key] for key in identifiers)
            or any(type(item[key]) is not int for key in numeric)
            or type(item["cycle"]) is not bool
            or type(item["captured_is_called"]) is not bool
            or item["installed_is_called"] is not True
            or item["cycle"]
            or item["increment"] == 0
            or item["cache"] <= 0
            or not item["minimum"] <= item["start"] <= item["maximum"]
            or not item["minimum"] <= item["captured_last_value"] <= item["maximum"]
            or not item["minimum"] <= item["installed_last_value"] <= item["maximum"]
            or item["next_generated_value"]
            != item["installed_last_value"] + item["increment"]
            or not item["minimum"] <= item["next_generated_value"] <= item["maximum"]
        ):
            raise ValueError
        constraint = item["constraint_identity"]
        definition = item["definition_sha256"]
        if (
            not isinstance(constraint, str)
            or not isinstance(definition, str)
            or bool(constraint) != bool(definition)
            or (
                constraint
                and (not _digest(constraint) or not _digest(definition))
            )
        ):
            raise ValueError
        identity = (item["schema"], item["sequence"])
        if identity in seen:
            raise ValueError
        seen.add(identity)


def _bind_rules(rule_proofs, commitments, broad, sequences, slice_ids):
    proof_ids = {item["constraint_identity"] for item in rule_proofs}
    committed = {item["constraint_identity"] for item in commitments}
    fenced = {item["constraint_identity"] for item in broad}
    sequenced = {
        item["constraint_identity"] for item in sequences
        if item["constraint_identity"] in proof_ids
    }
    expected_modes = {
        **{identity: "high_entropy_commitment" for identity in committed},
        **{identity: "broad_fence" for identity in fenced},
        **{identity: "sequence_high_water" for identity in sequenced},
    }
    if len(expected_modes) != len(committed | fenced | sequenced):
        raise ValueError
    for rule in rule_proofs:
        identity = rule["constraint_identity"]
        if expected_modes.pop(identity, None) != rule["reservation_mode"]:
            raise ValueError
        counts = rule["component_counts"]
        if (
            _json_digest(counts) != rule["owning_component_count_digest"]
            or sum(item["count"] for item in counts)
            != rule["qualifying_slice_row_count"]
            or not {item["component_id"] for item in counts} <= slice_ids
        ):
            raise ValueError
        if rule["reservation_mode"] == "broad_fence":
            matching = [
                item for item in broad if item["constraint_identity"] == identity
            ]
            if len(matching) != 1 or matching[0]["definition_sha256"] != rule[
                "broad_fence_definition_sha256"
            ]:
                raise ValueError
    if expected_modes:
        raise ValueError


def _contains_oracle(value):
    if isinstance(value, dict):
        return bool(_ORACLE_NAMES & set(value)) or any(
            _contains_oracle(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_oracle(item) for item in value)
    return False


def _json_digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode("utf-8")).hexdigest()


def _digest(value):
    return (
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
