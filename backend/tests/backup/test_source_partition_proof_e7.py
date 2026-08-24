import copy
import json
import uuid

import pytest

from apps.backup import source_partition_proof, source_verifier
from apps.backup.outer_manifest import verify_outer_manifest
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.source_partition_proof import (
    PROOF_VERSION,
    verify_source_partition_proof,
)
from tests.backup.e7_partition_test_helpers import (
    canonical_digest,
    detailed_manifest,
    digest,
    proof_without_signature,
    resign_manifest,
    signed_manifest,
    source_verifier_case,
)


HEADER_BINDINGS = (
    "protocol_version",
    "artifact_id",
    "capture_id",
    "source_database_identity",
    "source_server_identity",
    "frozen_dump_sha256",
    "physical_catalog_digest",
    "registry_digest",
    "frozen_population_ownership_digest",
    "readable_main_semantic_digest",
    "component_ciphertext_ledger_digest",
    "reservation_fence_ledger_digest",
    "user_closure_digest",
)


def _different_value(key):
    if key == "protocol_version":
        return "source-partition-proof-v2"
    if key in {"artifact_id", "capture_id"}:
        return str(uuid.uuid4())
    if key in {"source_database_identity", "source_server_identity"}:
        return f"different-{key}"
    return digest(f"different-{key}")


def _verified_proof(monkeypatch, tmp_path, *, rule_overrides=None):
    capture, reconstruction = source_verifier_case(
        tmp_path, rule_overrides=rule_overrides
    )
    monkeypatch.setattr(
        source_verifier, "_verify_main_non_occupancy", lambda _capture: None
    )
    return source_verifier.verify_and_sign_source_partition(
        capture,
        detailed_manifest=detailed_manifest(),
        reconstruction_pass=reconstruction,
    )


def _with_stale_signature(payload, proof):
    return {**payload, "proof_signature": proof["proof_signature"]}


def test_proof_records_complete_constraint_partition_and_verifier_identity(
    monkeypatch, tmp_path
):
    proof = _verified_proof(monkeypatch, tmp_path)
    rule = proof["unique_rules"][0]

    assert proof["protocol_version"] == PROOF_VERSION
    assert set(rule) == {
        "constraint_identity", "definition_sha256", "reservation_mode",
        "qualifying_source_row_count", "qualifying_main_row_count",
        "qualifying_slice_row_count", "owning_component_count_digest",
        "component_counts", "broad_fence_definition_sha256",
        "partition_complete", "main_disjoint", "reconstruction_equal",
    }
    assert rule["reservation_mode"] == "broad_fence"
    assert (
        rule["qualifying_source_row_count"],
        rule["qualifying_main_row_count"],
        rule["qualifying_slice_row_count"],
    ) == (3, 1, 2)
    assert rule["partition_complete"] == "pass"
    assert rule["main_disjoint"] == "pass"
    assert rule["reconstruction_equal"] == "pass"
    assert set(proof["verifier"]) == {
        "signing_key_fingerprint", "build", "oci_digest", "verified_at", "result",
    }
    assert proof["verifier"]["oci_digest"].startswith("sha256:")
    assert proof["verifier"]["verified_at"].endswith("+00:00")
    assert proof["verifier"]["result"] == "pass"
    assert verify_source_partition_proof(proof) is True


@pytest.mark.parametrize("binding", HEADER_BINDINGS)
def test_each_proof_header_binding_refuses_independently_when_tampered(
    monkeypatch, tmp_path, binding
):
    proof = _verified_proof(monkeypatch, tmp_path)
    expected = {key: proof[key] for key in HEADER_BINDINGS}
    candidate = copy.deepcopy(proof)
    candidate[binding] = _different_value(binding)

    with pytest.raises(BackupBuildError, match="source-partition proof"):
        verify_source_partition_proof(candidate, expected=expected)


def test_source_verifier_rejects_self_consistent_total_count_tampering(
    monkeypatch, tmp_path
):
    capture, reconstruction = source_verifier_case(
        tmp_path,
        rule_overrides={
            "qualifying_source_row_count": 4,
            "qualifying_main_row_count": 2,
        },
    )
    monkeypatch.setattr(
        source_verifier, "_verify_main_non_occupancy", lambda _capture: None
    )

    with pytest.raises(BackupBuildError, match="partition is incomplete"):
        source_verifier.verify_and_sign_source_partition(
            capture,
            detailed_manifest=detailed_manifest(),
            reconstruction_pass=reconstruction,
        )


def test_source_verifier_rejects_component_count_reconstruction_tampering(
    monkeypatch, tmp_path
):
    capture, reconstruction = source_verifier_case(tmp_path)
    counts = [{
        "component_id": capture.slice_entries[0]["component_id"], "count": 3
    }]
    rule = capture.reservation_capture.rule_proofs[0]
    rule.update({
        "qualifying_source_row_count": 4,
        "qualifying_slice_row_count": 3,
        "component_counts": counts,
        "owning_component_count_digest": canonical_digest(counts),
    })
    monkeypatch.setattr(
        source_verifier, "_verify_main_non_occupancy", lambda _capture: None
    )

    with pytest.raises(BackupBuildError, match="partition is incomplete"):
        source_verifier.verify_and_sign_source_partition(
            capture,
            detailed_manifest=detailed_manifest(),
            reconstruction_pass=reconstruction,
        )


def test_target_rejects_verifier_signed_fence_definition_replay(tmp_path):
    capture_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    manifest = signed_manifest(
        tmp_path / "selected",
        capture_id=capture_id,
        artifact_id=artifact_id,
    )
    donor = signed_manifest(
        tmp_path / "donor",
        capture_id=capture_id,
        artifact_id=artifact_id,
        fence_digest=digest("other-fence"),
    )
    manifest["source_partition_proof"] = donor["source_partition_proof"]

    with pytest.raises(BackupBuildError):
        verify_outer_manifest(resign_manifest(manifest))


@pytest.mark.parametrize(
    "binding",
    ("artifact_id", "capture_id", "component_ciphertext_ledger_digest", "registry_digest"),
)
def test_cross_run_component_or_registry_replay_is_invalid(
    tmp_path, binding
):
    capture_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    manifest = signed_manifest(
        tmp_path / "selected",
        capture_id=capture_id,
        artifact_id=artifact_id,
    )
    donor_options = {
        "capture_id": capture_id,
        "artifact_id": artifact_id,
    }
    if binding == "artifact_id":
        donor_options["artifact_id"] = uuid.uuid4()
    elif binding == "capture_id":
        donor_options["capture_id"] = uuid.uuid4()
    elif binding == "component_ciphertext_ledger_digest":
        donor_options["slice_digest"] = digest("other-slice-component")
    else:
        donor_options["registry_digest"] = digest("other-registry")
    donor = signed_manifest(tmp_path / "donor", **donor_options)
    manifest["source_partition_proof"] = donor["source_partition_proof"]

    with pytest.raises(BackupBuildError):
        verify_outer_manifest(resign_manifest(manifest))


def test_producer_module_has_no_public_build_sign_or_issue_capability():
    public_names = {
        name for name in dir(source_partition_proof) if not name.startswith("_")
    }

    assert not any(
        name.startswith(prefix)
        for name in public_names
        for prefix in ("build_", "sign_", "issue_")
    )
    assert callable(source_verifier.verify_and_sign_source_partition)


@pytest.mark.parametrize(
    "forbidden",
    ("raw_value", "canonical_key", "canonical_bytes", "per_value_digest"),
)
def test_low_entropy_rule_has_exact_fence_digest_and_no_enumerable_oracle(
    monkeypatch, tmp_path, forbidden
):
    proof = _verified_proof(monkeypatch, tmp_path)
    rule = proof["unique_rules"][0]
    assert rule["broad_fence_definition_sha256"] == digest(
        "broad-fence-definition"
    )
    assert forbidden not in json.dumps(rule, sort_keys=True)

    payload = proof_without_signature(proof)
    payload["unique_rules"][0][forbidden] = digest("enumerable-secret")
    with pytest.raises(BackupBuildError, match="malformed"):
        verify_source_partition_proof(_with_stale_signature(payload, proof))


def test_verifier_result_and_oci_identity_are_strict_not_producer_labels(
    monkeypatch, tmp_path
):
    proof = _verified_proof(monkeypatch, tmp_path)
    payload = proof_without_signature(proof)

    failed = copy.deepcopy(payload)
    failed["verifier"]["result"] = "producer-asserted-pass"
    with pytest.raises(BackupBuildError, match="identity or result"):
        verify_source_partition_proof(_with_stale_signature(failed, proof))

    mutable_label = copy.deepcopy(payload)
    mutable_label["verifier"]["oci_digest"] = "sha256:not-an-immutable-digest"
    with pytest.raises(BackupBuildError, match="identity or result"):
        verify_source_partition_proof(_with_stale_signature(mutable_label, proof))
