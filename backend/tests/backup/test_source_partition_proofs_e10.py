"""Lane E section 11 row 11: signed per-constraint source-proof acceptance."""

import base64
from copy import deepcopy
import uuid

import pytest

from apps.backup import host_supervisor, source_partition_proof
from apps.backup.recipient_selection import BackupBuildError
from tests.backup.e10_test_helpers import (
    resign_source_proof,
    signed_source_proof,
    valid_rule_proof,
)


def _unsigned(proof):
    value = deepcopy(proof)
    value.pop("proof_signature")
    return value


def test_only_source_verifier_owns_proof_construction_and_signing_names():
    for forbidden in (
        "build_unsigned_payload",
        "sign_source_partition_proof",
        "issue_verified_partition",
        "verifier_pass_token",
    ):
        assert not hasattr(source_partition_proof, forbidden)


def test_signature_and_verifier_identity_are_checked_independently():
    proof = signed_source_proof(rules=(valid_rule_proof(),))
    bad_signature = deepcopy(proof)
    bad_signature["proof_signature"]["value"] = base64.b64encode(b"x" * 64).decode()
    with pytest.raises(BackupBuildError, match="signed source-partition proof"):
        source_partition_proof.verify_source_partition_proof(bad_signature)

    wrong_verifier = _unsigned(proof)
    wrong_verifier["verifier"]["signing_key_fingerprint"] = "0" * 64
    wrong_verifier = resign_source_proof(wrong_verifier)
    with pytest.raises(BackupBuildError, match="signed source-partition proof"):
        source_partition_proof.verify_source_partition_proof(wrong_verifier)


@pytest.mark.parametrize(
    "binding",
    (
        "artifact_id",
        "capture_id",
        "physical_catalog_digest",
        "registry_digest",
        "readable_main_semantic_digest",
        "component_ciphertext_ledger_digest",
        "reservation_fence_ledger_digest",
        "user_closure_digest",
    ),
)
def test_each_artifact_capture_component_registry_and_digest_binding_rejects_replay(
    binding,
):
    proof = signed_source_proof(rules=(valid_rule_proof(),))
    expected = {binding: str(uuid.uuid4()) if binding.endswith("_id") else "f" * 64}

    with pytest.raises(BackupBuildError, match="signed source-partition proof"):
        source_partition_proof.verify_source_partition_proof(
            proof, expected=expected
        )


def test_cross_run_replay_rejects_even_with_a_valid_signature():
    first_artifact, first_capture = uuid.uuid4(), uuid.uuid4()
    proof = signed_source_proof(
        artifact_id=first_artifact,
        capture_id=first_capture,
        rules=(valid_rule_proof(),),
    )

    with pytest.raises(BackupBuildError):
        source_partition_proof.verify_source_partition_proof(
            proof,
            expected={
                "artifact_id": str(uuid.uuid4()),
                "capture_id": str(uuid.uuid4()),
            },
        )


@pytest.mark.parametrize(
    "mutation",
    ("source_count", "component_count", "fence_definition", "verifier_result"),
)
def test_count_fence_definition_and_result_tampering_fail_structurally(mutation):
    proof = _unsigned(signed_source_proof(rules=(valid_rule_proof(),)))
    rule = proof["unique_rules"][0]
    if mutation == "source_count":
        rule["qualifying_source_row_count"] += 1
    elif mutation == "component_count":
        rule["component_counts"][0]["count"] += 1
    elif mutation == "fence_definition":
        rule["broad_fence_definition_sha256"] = "not-a-digest"
    else:
        proof["verifier"]["result"] = "producer-asserted"

    with pytest.raises(BackupBuildError):
        source_partition_proof._validate_unsigned(proof)


@pytest.mark.parametrize(
    "oracle_name",
    ("raw_value", "canonical_key", "canonical_bytes", "value_digest", "per_value_digest"),
)
def test_no_low_entropy_raw_value_or_value_derived_oracle_can_enter_a_rule(
    oracle_name,
):
    proof = _unsigned(signed_source_proof(rules=(valid_rule_proof(),)))
    proof["unique_rules"][0][oracle_name] = "short-enumerable-secret"

    with pytest.raises(BackupBuildError, match="unique-rule entry"):
        source_partition_proof._validate_unsigned(proof)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC GAP: no Lane E host cutover coordinator validates the source proof "
        "before calling the pointer primitive"
    ),
)
def test_source_proof_rejection_precedes_pointer_mutation():
    coordinator = getattr(host_supervisor, "prepare_compound_cutover", None)
    assert callable(coordinator)
    pointer_calls = []
    proof = signed_source_proof(rules=(valid_rule_proof(),))
    proof["proof_signature"]["value"] = base64.b64encode(b"x" * 64).decode()

    with pytest.raises(BackupBuildError):
        coordinator(
            proof=proof,
            pointer_mutation=lambda *_args: pointer_calls.append(True),
        )
    assert pointer_calls == []
