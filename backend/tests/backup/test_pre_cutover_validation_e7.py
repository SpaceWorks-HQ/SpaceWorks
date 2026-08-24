import copy
import hashlib
import json
import uuid
from types import SimpleNamespace

import pytest

from apps.backup import outer_manifest, source_verifier, storage
from apps.backup.import_preflight import (
    ImportPreflightError,
    validate_import_preflight,
)
from apps.backup.models import BackupArchive
from apps.backup.outer_manifest import verify_outer_manifest
from apps.backup.postgres_client import server_major
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.reservation_registry import component_canonicalizer_identities
from apps.backup.source_partition_proof import verify_source_partition_proof
from apps.hardware_requests.models import HardwareRequest
from apps.ed25519 import encode_key, generate_keypair
from tests.backup.e7_partition_test_helpers import (
    detailed_manifest,
    digest,
    proof_without_signature,
    resign_manifest,
    signed_manifest,
    source_verifier_case,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _import_refused_before_pointer(monkeypatch, tmp_path, manifest, *, expected=None):
    encrypted = tmp_path / f"{uuid.uuid4()}.tar.age"
    encrypted.write_bytes(b"e7 outer ciphertext")
    expected = expected or hashlib.sha256(encrypted.read_bytes()).hexdigest()
    bundle = tmp_path / f"bundle-{uuid.uuid4()}"
    bundle.mkdir()
    manifest_file = bundle / "manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    continuity_file = bundle / "continuity-secrets.json"
    continuity_file.write_text("{}", encoding="utf-8")
    uploads = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: uploads.append(args))
    monkeypatch.setattr(storage, "delete_archive", lambda *_args: None)

    with pytest.raises(ImportPreflightError):
        validate_import_preflight(
            encrypted_file=encrypted,
            bundle=bundle,
            manifest_file=manifest_file,
            continuity_secrets_file=continuity_file,
            expected_sha256=expected,
        )

    assert uploads == []
    assert not BackupArchive.objects.filter(pk=manifest["artifact_id"]).exists()


def test_outer_ciphertext_digest_is_checked_before_any_final_key_write(
    monkeypatch, tmp_path
):
    _import_refused_before_pointer(
        monkeypatch,
        tmp_path,
        signed_manifest(tmp_path / "manifest"),
        expected="0" * 64,
    )


def test_manifest_uses_host_installed_trust_key_before_any_final_key_write(
    monkeypatch, settings, tmp_path
):
    manifest = signed_manifest(tmp_path / "manifest")
    _private, other_public = generate_keypair()
    settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY = encode_key(other_public)

    _import_refused_before_pointer(monkeypatch, tmp_path, manifest)


@pytest.mark.parametrize("tamper", ("signature", "fingerprint"))
def test_canonical_detached_proof_signature_and_fingerprint_precede_pointer_write(
    monkeypatch, tmp_path, tamper
):
    manifest = signed_manifest(tmp_path / "manifest")
    proof = copy.deepcopy(manifest["source_partition_proof"])
    if tamper == "signature":
        proof["proof_signature"]["value"] = "AAAA"
    else:
        proof["proof_signature"]["signer_fingerprint"] = digest(
            "untrusted-verifier"
        )
    manifest["source_partition_proof"] = proof

    _import_refused_before_pointer(
        monkeypatch, tmp_path, resign_manifest(manifest)
    )


@pytest.mark.parametrize(
    "binding",
    (
        "source_database_identity",
        "source_server_identity",
        "frozen_dump_sha256",
        "frozen_population_ownership_digest",
    ),
)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC BUG: target proof binding omits the signed source database/server, "
        "frozen dump, and frozen-population ownership facts"
    ),
)
def test_target_has_independent_selected_artifact_binding_for_source_facts(
    monkeypatch, tmp_path, binding
):
    capture_id = uuid.uuid4()
    archive_id = uuid.uuid4()
    manifest = _verifier_manifest(
        monkeypatch,
        tmp_path / "selected",
        capture_id=capture_id,
        archive_id=archive_id,
    )
    donor = _verifier_manifest(
        monkeypatch,
        tmp_path / "donor",
        capture_id=capture_id,
        archive_id=archive_id,
        changed_source_fact=binding,
    )
    manifest["source_partition_proof"] = donor["source_partition_proof"]

    with pytest.raises(BackupBuildError):
        verify_outer_manifest(resign_manifest(manifest))


def _verifier_manifest(
    monkeypatch, root, *, capture_id, archive_id, changed_source_fact=None
):
    archive = SimpleNamespace(pk=archive_id)
    capture, reconstruction = source_verifier_case(
        root, capture_id=capture_id, archive=archive
    )
    if changed_source_fact == "frozen_population_ownership_digest":
        capture.frozen_population = ("different-frozen-population",)
    elif changed_source_fact:
        replacements = {
            "source_database_identity": "different-source-database",
            "source_server_identity": "postgresql:160010:different-server",
            "frozen_dump_sha256": digest("different-frozen-dump"),
        }
        setattr(capture, changed_source_fact, replacements[changed_source_fact])
    monkeypatch.setattr(
        source_verifier, "_verify_main_non_occupancy", lambda _capture: None
    )
    detailed = detailed_manifest()
    capture.source_partition_proof = (
        source_verifier.verify_and_sign_source_partition(
            capture,
            detailed_manifest=detailed,
            reconstruction_pass=reconstruction,
        )
    )
    return outer_manifest.build_outer_manifest(
        archive=archive,
        capture=capture,
        detailed_manifest=detailed,
        root=root,
    )


def _unknown_canonicalizer_manifest(tmp_path):
    manifest = signed_manifest(tmp_path)
    rule = next(
        item for item in load_unique_rules()
        if item.table == HardwareRequest._meta.db_table
        and item.components[0].source_column == "public_token"
    )
    slice_id = manifest["slice_components"][0]["component_id"]
    manifest["broad_fence_scopes"] = []
    manifest["reservation_commitments"] = [{
        "constraint_identity": rule.identity,
        "definition_sha256": rule.definition_sha256,
        "canonicalizer_identity": digest("unknown-canonicalizer-set"),
        "key_component_identities": list(
            component_canonicalizer_identities(rule, server_major())
        ),
        "component_commitments": [{
            "component_id": slice_id,
            "commitments": [digest("reserved-value")],
        }],
    }]
    return resign_manifest(manifest)


def _invalid_manifest(tmp_path, reason):
    manifest = signed_manifest(tmp_path)
    proof = manifest["source_partition_proof"]
    if reason == "missing-rule":
        proof["unique_rules"] = []
    elif reason == "unknown-canonicalizer":
        return _unknown_canonicalizer_manifest(tmp_path / "unknown")
    elif reason == "count-mismatch":
        proof["unique_rules"][0].update({
            "qualifying_source_row_count": 4,
            "qualifying_main_row_count": 2,
        })
    elif reason == "digest-mismatch":
        manifest["main_component"]["semantic_digest"] = digest("wrong-main")
    elif reason == "invalid-result":
        proof["verifier"]["result"] = "fail"
    elif reason == "missing-fence":
        manifest["broad_fence_scopes"] = []
    return resign_manifest(manifest)


@pytest.mark.parametrize(
    "reason",
    (
        "missing-rule", "unknown-canonicalizer", "count-mismatch",
        "digest-mismatch", "invalid-result", "missing-fence",
    ),
)
def test_every_pre_cutover_refusal_happens_before_pointer_mutation(
    monkeypatch, tmp_path, reason
):
    _import_refused_before_pointer(
        monkeypatch,
        tmp_path,
        _invalid_manifest(tmp_path / reason, reason),
    )


def test_unknown_target_canonicalizer_cannot_be_authorized_by_both_signatures(
    tmp_path,
):
    with pytest.raises(BackupBuildError):
        verify_outer_manifest(_unknown_canonicalizer_manifest(tmp_path))


def test_non_pass_proof_cannot_reach_the_target_as_a_shortcut(tmp_path):
    proof = signed_manifest(tmp_path)["source_partition_proof"]
    payload = proof_without_signature(proof)
    payload["unique_rules"][0]["reconstruction_equal"] = "producer-asserted"
    candidate = {**payload, "proof_signature": proof["proof_signature"]}

    with pytest.raises(BackupBuildError, match="non-pass"):
        verify_source_partition_proof(candidate)
