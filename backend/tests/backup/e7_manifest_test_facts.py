"""Real, empty E7 reservation/proof facts for older manifest contract tests."""

import base64
import hashlib

from django.conf import settings
from django.utils import timezone

from apps.backup.digests import sha256_file
from apps.backup.outer_manifest_facts import (
    component_ciphertext_ledger,
    digest_json,
    reservation_fence_ledger,
)
from apps.backup.source_partition_proof import (
    PROOF_VERSION,
    _signature_payload,
    _validate_unsigned,
)
from apps.backup.source_reservations import ReservationCapture
from apps.ed25519 import decode_key, fingerprint_public_key, sign_bytes


EMPTY_REGISTRY_DIGEST = hashlib.sha256(b"e7-empty-test-registry").hexdigest()


def empty_reservation_capture():
    return ReservationCapture(
        run_salt=b"s" * 32,
        registry_digest=EMPTY_REGISTRY_DIGEST,
        commitments=(),
        broad_fences=(),
        relationship_fences=(),
        object_namespace_fences=(),
        sequence_facts=(),
        rule_proofs=(),
        raw_keys_by_component={},
    )


def bind_source_partition_proof(capture, archive, detailed_manifest, root):
    component_ledger = component_ciphertext_ledger(
        capture, detailed_manifest, root
    )
    reservation_ledger = reservation_fence_ledger(capture)
    build = detailed_manifest["build"]
    oci_digest = detailed_manifest["oci_digest"]
    rule_proofs = [
        {
            **rule,
            "partition_complete": "pass",
            "main_disjoint": "pass",
            "reconstruction_equal": "pass",
        }
        for rule in capture.reservation_capture.rule_proofs
    ]
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
        "artifact_id": str(archive.pk),
        "capture_id": str(capture.capture_id),
        "source_database_identity": "e7-fixture-source",
        "source_server_identity": "postgresql:e7-fixture",
        "frozen_dump_sha256": (
            getattr(capture, "source_dump_sha256", "")
            or sha256_file(root / "database.dump")
        ),
        "physical_catalog_digest": capture.source_catalog_digest,
        "registry_digest": capture.reservation_capture.registry_digest,
        "frozen_population_ownership_digest": "9" * 64,
        "readable_main_semantic_digest": digest_json(capture.expected_main_ledger),
        "component_ciphertext_ledger_digest": digest_json(component_ledger),
        "reservation_fence_ledger_digest": digest_json(reservation_ledger),
        "user_closure_digest": capture.user_closure_digest,
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
    capture.source_partition_proof = {
        **payload,
        "proof_signature": {
            "algorithm": "ed25519",
            "signer_fingerprint": fingerprint_public_key(public),
            "value": base64.b64encode(
                sign_bytes(_signature_payload(payload), private)
            ).decode("ascii"),
        },
    }
    return capture.source_partition_proof
