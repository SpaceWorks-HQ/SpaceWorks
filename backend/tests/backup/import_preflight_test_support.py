from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import tarfile
import uuid

from apps.backup import outer_manifest
from apps.backup.archive_payload import CONTINUITY_KEYS


SOURCE_HASH = "a" * 64
POSTGRES_MAJOR = 16


@dataclass
class ImportFixture:
    root: Path
    encrypted: Path
    bundle: Path
    manifest_file: Path
    secrets_file: Path
    manifest: dict
    secrets: dict
    members: dict

    @property
    def expected_sha256(self):
        return hashlib.sha256(self.encrypted.read_bytes()).hexdigest()

    def write(self, *, sign=True):
        if sign:
            unsigned = dict(self.manifest)
            unsigned.pop("archive_signature", None)
            ledger = [
                unsigned["main_component"], *unsigned["slice_components"]
            ]
            self.manifest = unsigned
            self.manifest["archive_signature"] = outer_manifest._signature(
                unsigned, ledger
            )
        manifest_bytes = json.dumps(self.manifest, sort_keys=True).encode()
        secrets_bytes = json.dumps(self.secrets, sort_keys=True).encode()
        self.manifest_file.write_bytes(manifest_bytes)
        self.secrets_file.write_bytes(secrets_bytes)
        payloads = {
            **self.members,
            "manifest.json": manifest_bytes,
            "keys/env.json": secrets_bytes,
        }
        with tarfile.open(self.bundle, "w") as archive:
            for name, payload in payloads.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))


def make_import_fixture(tmp_path):
    root = tmp_path / "import-fixture"
    root.mkdir()
    encrypted = root / "archive.tar.age"
    bundle = root / "archive.tar"
    manifest_file = root / "manifest.json"
    secrets_file = root / "keys-env.json"
    encrypted.write_bytes(b"authenticated age ciphertext")
    database = b"readable main database"
    slice_bytes = b"opaque tenant slice"
    artifact_id = uuid.uuid4()
    capture_id = uuid.uuid4()
    main_id = outer_manifest.component_id(capture_id, "main")
    slice_id = outer_manifest.component_id(capture_id, "slice", 7)
    main = {
        "component_id": main_id,
        "kind": "main",
        "path": "database.dump",
        "size_bytes": len(database),
        "ciphertext_sha256": hashlib.sha256(database).hexdigest(),
        "schema_catalog_digest": "b" * 64,
        "sequence_policy": "source-high-water-over-all-components",
        "recipient_fingerprints": [],
    }
    slice_component = {
        "component_id": slice_id,
        "kind": "slice",
        "makerspace_id": 7,
        "ciphertext_path": f"slices/{slice_id}.tar.age",
        "size_bytes": len(slice_bytes),
        "ciphertext_sha256": hashlib.sha256(slice_bytes).hexdigest(),
        "recipient_fingerprints": ["c" * 64],
    }
    manifest = {
        "format": "spaceworks-phase5a-v3",
        "protocol_version": outer_manifest.PROTOCOL_VERSION,
        "artifact_id": str(artifact_id),
        "capture_id": str(capture_id),
        "source_timestamp": "2026-08-24T00:00:00+00:00",
        "build_identity": {
            "build": {"source_hash": SOURCE_HASH}, "oci_digest": ""
        },
        "postgres": {
            "source_server_major": POSTGRES_MAJOR,
            "client": f"pg_dump (PostgreSQL) {POSTGRES_MAJOR}.4",
        },
        "makerspace_sets": {
            "retained": [7], "readable_main": [], "sovereign": [7]
        },
        "main_component": main,
        "slice_components": [slice_component],
        "object_ledgers": [
            {"component_id": main_id, "count": 0, "digest": "d" * 64},
            {"component_id": slice_id, "count": 0, "digest": "e" * 64},
        ],
        "content_ledgers": [
            {"component_id": main_id, "count": 2, "digest": "f" * 64},
            {"component_id": slice_id, "count": 1, "digest": "1" * 64},
        ],
        "reservation_commitments": [],
        "broad_fence_scopes": [],
        "not_restored_seeds": [{
            "component_id": slice_id, "makerspace_id": 7, "state": "pending"
        }],
        "user_closure_digest": "2" * 64,
        "archive_id": str(artifact_id),
        "scope": "deployment",
        "age_encrypted": True,
        "snapshot_at": "2026-08-24T00:00:00+00:00",
        "build": {"source_hash": SOURCE_HASH},
        "oci_digest": "",
        "covered_makerspace_ids": [],
        "excluded_makerspace_ids": [7],
        "partial": True,
        "recipient_fingerprints": [],
        "slices": [{
            "slice_id": slice_id,
            "component_id": slice_id,
            "makerspace_id": 7,
            "path": slice_component["ciphertext_path"],
            "size_bytes": slice_component["size_bytes"],
            "ciphertext_sha256": slice_component["ciphertext_sha256"],
            "recipient_fingerprints": slice_component["recipient_fingerprints"],
            "custody_state": "healthy",
        }],
        "contents": [
            {
                "path": main["path"], "size": main["size_bytes"],
                "sha256": main["ciphertext_sha256"],
            },
            {
                "path": slice_component["ciphertext_path"],
                "size": slice_component["size_bytes"],
                "sha256": slice_component["ciphertext_sha256"],
            },
        ],
    }
    fixture = ImportFixture(
        root=root,
        encrypted=encrypted,
        bundle=bundle,
        manifest_file=manifest_file,
        secrets_file=secrets_file,
        manifest=manifest,
        secrets={name: f"value-for-{name}" for name in CONTINUITY_KEYS},
        members={
            main["path"]: database,
            slice_component["ciphertext_path"]: slice_bytes,
        },
    )
    fixture.write()
    return fixture


def preflight_kwargs(fixture):
    return {
        "encrypted_file": fixture.encrypted,
        "bundle": fixture.bundle,
        "manifest_file": fixture.manifest_file,
        "continuity_secrets_file": fixture.secrets_file,
        "expected_sha256": fixture.expected_sha256,
    }
