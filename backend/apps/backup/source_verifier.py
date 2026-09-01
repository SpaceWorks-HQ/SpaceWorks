"""Independent source-side verifier that alone may sign an E7 partition proof."""

import base64
import hashlib
import json

from django.conf import settings
from django.utils import timezone

from apps.backup.outer_manifest_facts import (
    component_ciphertext_ledger,
    digest_json,
    reservation_fence_ledger,
)
from apps.backup.physical_catalog import (
    catalog_difference,
    catalog_digest,
    physical_catalog_ledger,
)
from apps.backup.postgres_client import server_major
from apps.backup.projection_databases import restore_dump, temporary_database
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.reservation_keys import reservation_commitment
from apps.backup.source_partition_proof import (
    PROOF_VERSION,
    _signature_payload,
    _validate_unsigned,
)
from apps.backup.source_reservations import _evaluate_rule
from apps.ed25519 import (
    Ed25519Error,
    decode_key,
    fingerprint_public_key,
    sign_bytes,
)


def verify_and_sign_source_partition(
    capture, *, detailed_manifest, reconstruction_pass
):
    """Recheck candidate/catalog/reservations, then construct the sole signed proof."""

    if not capture.slice_entries or not capture.unsealed_slices:
        raise BackupBuildError("The source verifier lacks both plaintext and sealed slices.")
    _verify_main_non_occupancy(capture)
    component_ledger = component_ciphertext_ledger(
        capture, detailed_manifest, capture.root
    )
    reservation_ledger = reservation_fence_ledger(capture)
    rule_proofs = []
    for rule in capture.reservation_capture.rule_proofs:
        identity = rule["constraint_identity"]
        reconstructed_components = reconstruction_pass.component_counts.get(
            identity, {}
        )
        expected_components = {
            item["component_id"]: item["count"]
            for item in rule["component_counts"]
        }
        if (
            rule["qualifying_source_row_count"]
            != rule["qualifying_main_row_count"] + rule["qualifying_slice_row_count"]
            or _digest(rule["component_counts"])
            != rule["owning_component_count_digest"]
            or reconstruction_pass.source_counts.get(identity)
            != rule["qualifying_source_row_count"]
            or reconstruction_pass.main_counts.get(identity)
            != rule["qualifying_main_row_count"]
            or reconstructed_components != expected_components
        ):
            raise BackupBuildError("The source reservation partition is incomplete.")
        _verify_reconstructed_keys(capture, reconstruction_pass, identity)
        rule_proofs.append({
            **rule,
            "partition_complete": "pass",
            "main_disjoint": "pass",
            "reconstruction_equal": "pass",
        })
    object_facts = {
        "population": capture.frozen_population,
        "references": [
            {
                "bucket_kind": item.bucket_kind,
                "site": item.site,
                "candidate_owner": item.candidate_owner,
                "makerspace_id": item.canonical_makerspace_id,
                "coordination_policy": item.coordination_policy,
            }
            for item in capture.object_plan.references
        ],
    }
    header = {
        "artifact_id": str(capture.archive.pk),
        "capture_id": str(capture.capture_id),
        "source_database_identity": capture.source_database_identity,
        "source_server_identity": capture.source_server_identity,
        "frozen_dump_sha256": capture.source_dump_sha256,
        "physical_catalog_digest": capture.source_catalog_digest,
        "registry_digest": capture.reservation_capture.registry_digest,
        "frozen_population_ownership_digest": _digest(object_facts),
        "readable_main_semantic_digest": _digest(capture.expected_main_ledger),
        "component_ciphertext_ledger_digest": digest_json(component_ledger),
        "reservation_fence_ledger_digest": digest_json(reservation_ledger),
        "user_closure_digest": capture.user_closure_digest,
    }
    build = detailed_manifest.get("build")
    oci_digest = detailed_manifest.get("oci_digest")
    if not build:
        raise BackupBuildError("The immutable verifier build identity is required.")
    try:
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
            **header,
            "verifier": {
                "signing_key_fingerprint": fingerprint_public_key(public),
                "build": build,
                "oci_digest": oci_digest,
                "verified_at": timezone.now().isoformat(),
                "result": "pass",
            },
            "unique_rules": rule_proofs,
        }
        _validate_unsigned(payload)
        signature = sign_bytes(_signature_payload(payload), private)
    except Ed25519Error as exc:
        raise BackupBuildError("The source verifier signing identity is invalid.") from exc
    return {
        **payload,
        "proof_signature": {
            "algorithm": "ed25519",
            "signer_fingerprint": fingerprint_public_key(public),
            "value": base64.b64encode(signature).decode("ascii"),
        },
    }


def _verify_reconstructed_keys(capture, reconstruction_pass, constraint_identity):
    expected = {}
    for component_id, entries in capture.reservation_capture.raw_keys_by_component.items():
        values = sorted(
            framed for identity, framed in entries
            if identity == constraint_identity
        )
        raw = b"".join(len(value).to_bytes(8, "big") + value for value in values)
        expected[component_id] = hashlib.sha256(raw).hexdigest()
    actual = reconstruction_pass.component_key_digests.get(constraint_identity, {})
    if set(actual) != set(expected):
        raise BackupBuildError(
            "Reconstructed PostgreSQL reservation-key component coverage is incomplete."
        )
    for component_id, digest in actual.items():
        if digest != expected[component_id]:
            raise BackupBuildError(
                "Reconstructed PostgreSQL reservation keys differ from the source ledger."
            )


def _verify_main_non_occupancy(capture):
    expected_commitments = {
        commitment
        for item in capture.reservation_capture.commitments
        for component in item["component_commitments"]
        for commitment in component["commitments"]
    }
    rules = {
        item.identity: item for item in load_unique_rules("default")
    }
    with temporary_database("reservation_main") as (using, database_name):
        restore_dump(capture.root / "database.dump", database_name)
        restored_catalog = physical_catalog_ledger(using)
        _assert_catalog_reproduced(
            capture.source_catalog_ledger,
            capture.source_catalog_digest,
            restored_catalog,
        )
        restored_rules = {item.identity: item for item in load_unique_rules(using)}
        for proof in capture.reservation_capture.rule_proofs:
            rule = restored_rules.get(proof["constraint_identity"])
            if (
                rule is None
                or rule.definition_payload()
                != rules[rule.identity].definition_payload()
            ):
                raise BackupBuildError("A unique rule was not reproduced in the readable main.")
            if proof["reservation_mode"] != "high_entropy_commitment":
                continue
            model = next(
                item.model for item in __import__(
                    "apps.backup.main_projection_registry", fromlist=["table_rules"]
                ).table_rules() if item.model._meta.db_table == rule.table
            )
            framed = _evaluate_rule(
                using, rule, model._base_manager.using(using).all(), server_major(),
                canonicalize=True,
            )
            actual = {
                reservation_commitment(capture.reservation_capture.run_salt, item)
                for item in framed if item is not None
            }
            if actual.intersection(expected_commitments):
                raise BackupBuildError("The readable main occupies a reserved unique value.")
        _verify_sequence_high_water(using, capture.reservation_capture.sequence_facts)


def _assert_catalog_reproduced(expected, expected_digest, actual):
    if catalog_digest(actual) == expected_digest:
        return
    difference = catalog_difference(expected, actual)
    raise BackupBuildError(
        "The readable main changed the physical catalog definition: "
        + json.dumps(difference, separators=(",", ":"), default=str)
    )


def _verify_sequence_high_water(using, facts):
    from django.db import connections

    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for fact in facts:
            cursor.execute(
                f"SELECT last_value, is_called FROM "
                f"{quote(fact['schema'])}.{quote(fact['sequence'])}"
            )
            if list(cursor.fetchone()) != [
                fact["installed_last_value"], fact["installed_is_called"]
            ]:
                raise BackupBuildError("Readable-main sequence high-water is incorrect.")


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()
