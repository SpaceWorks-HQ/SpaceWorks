import uuid

import pytest

from apps.backup import source_partition_proof
from apps.backup.outer_reservation_validation import _validate_commitments
from apps.backup.postgres_client import server_major
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.reservation_registry import (
    canonicalizer_identity,
    component_canonicalizer_identities,
)
from apps.hardware_requests.models import HardwareRequest


pytestmark = pytest.mark.django_db(transaction=True)


def test_producer_module_exposes_no_verifier_pass_or_signing_capability():
    for public_name in (
        "verifier_pass_token",
        "issue_verified_partition",
        "sign_source_partition_proof",
    ):
        assert not hasattr(source_partition_proof, public_name)


def test_unique_rule_catalog_never_repeats_or_treats_foreign_keys_as_unique_rules():
    rules = load_unique_rules()

    assert len({rule.identity for rule in rules}) == len(rules)
    assert all(
        not rule.exact_constraint_definition.startswith("FOREIGN KEY")
        for rule in rules
    )


def test_oci_identity_requires_one_exact_sha256_digest():
    payload = {
        "protocol_version": source_partition_proof.PROOF_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "capture_id": str(uuid.uuid4()),
        "source_database_identity": "source",
        "source_server_identity": "postgresql:16",
        "frozen_dump_sha256": "a" * 64,
        "physical_catalog_digest": "b" * 64,
        "registry_digest": "c" * 64,
        "frozen_population_ownership_digest": "d" * 64,
        "readable_main_semantic_digest": "e" * 64,
        "component_ciphertext_ledger_digest": "f" * 64,
        "reservation_fence_ledger_digest": "1" * 64,
        "user_closure_digest": "2" * 64,
        "verifier": {
            "signing_key_fingerprint": "3" * 64,
            "build": "e7",
            "oci_digest": "sha256:not-a-digest",
            "verified_at": "2026-08-23T00:00:00+00:00",
            "result": "pass",
        },
        "unique_rules": [],
    }

    with pytest.raises(BackupBuildError, match="identity or result"):
        source_partition_proof._validate_unsigned(payload)


def test_unknown_commitment_canonicalizer_is_structurally_refused():
    rule = next(
        item for item in load_unique_rules()
        if item.table == HardwareRequest._meta.db_table
        and item.components[0].source_column == "public_token"
    )
    component_id = str(uuid.uuid4())
    fact = {
        "constraint_identity": rule.identity,
        "definition_sha256": rule.definition_sha256,
        "canonicalizer_identity": "0" * 64,
        "key_component_identities": list(
            component_canonicalizer_identities(rule, server_major())
        ),
        "component_commitments": [{
            "component_id": component_id,
            "commitments": ["4" * 64],
        }],
    }
    assert fact["canonicalizer_identity"] != canonicalizer_identity(
        rule, server_major()
    )

    with pytest.raises(ValueError):
        _validate_commitments([fact], {component_id})
