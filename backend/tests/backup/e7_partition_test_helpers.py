import copy
import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from django.utils import timezone

from apps.backup import outer_manifest
from apps.backup.digests import sha256_file
from apps.backup.outer_manifest_validation import component_id
from apps.backup.source_reservations import ReservationCapture
from tests.backup.e7_manifest_test_facts import bind_source_partition_proof


MAKERSPACE_ID = 701


def digest(label):
    return hashlib.sha256(str(label).encode()).hexdigest()


def canonical_digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def signed_manifest(
    root, *, capture_id=None, artifact_id=None, registry_digest=None,
    slice_digest=None, fence_digest=None,
):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "database.dump").write_bytes(b"e7 readable main")
    archive = SimpleNamespace(pk=artifact_id or uuid.uuid4())
    capture, _reconstruction = source_verifier_case(
        root,
        capture_id=capture_id,
        archive=archive,
        registry_digest=registry_digest,
        slice_digest=slice_digest,
        fence_digest=fence_digest,
    )
    detailed = detailed_manifest()
    bind_source_partition_proof(capture, archive, detailed, root)
    return outer_manifest.build_outer_manifest(
        archive=archive,
        capture=capture,
        detailed_manifest=detailed,
        root=root,
    )


def source_verifier_case(
    root, *, capture_id=None, archive=None, rule_overrides=None,
    registry_digest=None, slice_digest=None, fence_digest=None,
):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    dump = root / "database.dump"
    if not dump.exists():
        dump.write_bytes(b"e7 readable main")
    capture_id = capture_id or uuid.uuid4()
    archive = archive or SimpleNamespace(pk=uuid.uuid4())
    slice_id = component_id(capture_id, "slice", MAKERSPACE_ID)
    counts = [{"component_id": slice_id, "count": 2}]
    fence_digest = fence_digest or digest("broad-fence-definition")
    rule = {
        "constraint_identity": digest("constraint-identity"),
        "definition_sha256": digest("constraint-definition"),
        "reservation_mode": "broad_fence",
        "qualifying_source_row_count": 3,
        "qualifying_main_row_count": 1,
        "qualifying_slice_row_count": 2,
        "owning_component_count_digest": canonical_digest(counts),
        "component_counts": counts,
        "broad_fence_definition_sha256": fence_digest,
        "partition_complete": "pending",
        "main_disjoint": "pending",
        "reconstruction_equal": "pending",
    }
    rule.update(rule_overrides or {})
    reservation_capture = ReservationCapture(
        run_salt=b"s" * 32,
        registry_digest=registry_digest or digest("registry-v1"),
        commitments=(),
        broad_fences=({
            "version": "b1-broad-unique-fence-v1",
            "constraint_identity": rule["constraint_identity"],
            "schema": "public",
            "table": "makerspaces_makerspace",
            "columns": ["slug"],
            "operations": ["insert", "update"],
            "component_ids": [slice_id],
            "component_counts": counts,
            "definition_sha256": fence_digest,
        },),
        relationship_fences=(),
        object_namespace_fences=(),
        sequence_facts=(),
        rule_proofs=(rule,),
        raw_keys_by_component={},
    )
    frozen = SimpleNamespace(
        makerspace_id=MAKERSPACE_ID, custody_state="healthy"
    )
    capture = SimpleNamespace(
        archive=archive,
        capture_id=capture_id,
        root=root,
        source_database_identity="spaceworks_source",
        source_server_identity="postgresql:160010:server-701",
        source_dump_sha256=sha256_file(dump),
        source_catalog_digest=digest("physical-catalog"),
        source_catalog_ledger=(),
        expected_main_ledger={"catalog": "verified"},
        user_closure_digest=digest("user-closure"),
        frozen_population_ids=(MAKERSPACE_ID,),
        frozen_population=(),
        frozen_slices=(frozen,),
        platform_recipients=frozenset({"age1platforme7testrecipient"}),
        slice_entries=[{
            "component_id": slice_id,
            "makerspace_id": MAKERSPACE_ID,
            "path": f"slices/{slice_id}.tar.age",
            "size_bytes": 23,
            "ciphertext_sha256": slice_digest or digest("slice-ciphertext"),
            "recipient_fingerprints": [digest("tenant-recipient")],
            "object_ledger_count": 0,
            "object_ledger_digest": digest("slice-object-ledger"),
            "content_ledger_count": 0,
            "content_ledger_digest": digest("slice-content-ledger"),
        }],
        unsealed_slices=(SimpleNamespace(makerspace_id=MAKERSPACE_ID),),
        object_plan=SimpleNamespace(references=()),
        reservation_capture=reservation_capture,
        source_partition_proof=None,
    )
    reconstruction = SimpleNamespace(
        source_counts={rule["constraint_identity"]: 3},
        main_counts={rule["constraint_identity"]: 1},
        component_counts={rule["constraint_identity"]: {slice_id: 2}},
        component_key_digests={rule["constraint_identity"]: {}},
    )
    return capture, reconstruction


def detailed_manifest():
    return {
        "format": "spaceworks-phase5a-v3",
        "snapshot_at": timezone.now().isoformat(),
        "build": {"source_hash": digest("e7-verifier-build")},
        "oci_digest": f"sha256:{digest('e7-verifier-image')}",
        "postgres": {
            "source_server_major": 16,
            "client": "pg_dump (PostgreSQL) 16.10",
            "supported_source_majors": [14, 15, 16, 17],
        },
        "recipient_fingerprints": [digest("platform-recipient")],
        "storage": {"objects": []},
        "contents": [],
    }


def proof_without_signature(proof, *, header_overrides=None, rule_overrides=None):
    payload = copy.deepcopy(proof)
    payload.pop("proof_signature")
    payload.update(header_overrides or {})
    if rule_overrides:
        payload["unique_rules"][0].update(rule_overrides)
    return payload


def resign_manifest(manifest):
    result = copy.deepcopy(manifest)
    result.pop("archive_signature", None)
    components = [result["main_component"], *result["slice_components"]]
    result["archive_signature"] = outer_manifest._signature(result, components)
    return result
