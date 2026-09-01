from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import uuid

from apps.backup import outer_manifest
from apps.backup.archive_payload import CONTINUITY_KEYS
from tests.backup.e7_manifest_test_facts import (
    bind_source_partition_proof,
    empty_reservation_capture,
)


SOURCE_HASH = "a" * 64
POSTGRES_MAJOR = 16
SUPPORTED_SOURCE_MAJORS = [14, 15, 16, 17]


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
    slice_id = outer_manifest.component_id(capture_id, "slice", 7)
    slice_path = f"slices/{slice_id}.tar.age"
    slice_digest = hashlib.sha256(slice_bytes).hexdigest()
    (root / "database.dump").write_bytes(database)
    capture = SimpleNamespace(
        capture_id=capture_id,
        frozen_population_ids=(7,),
        frozen_slices=(SimpleNamespace(
            makerspace_id=7, custody_state="healthy"
        ),),
        expected_main_ledger={"fixture": "import-preflight"},
        source_catalog_digest="b" * 64,
        platform_recipients=frozenset(),
        reservation_capture=empty_reservation_capture(),
        source_partition_proof=None,
        user_closure_digest="2" * 64,
        slice_entries=[{
            "component_id": slice_id,
            "makerspace_id": 7,
            "path": slice_path,
            "size_bytes": len(slice_bytes),
            "ciphertext_sha256": slice_digest,
            "recipient_fingerprints": ["c" * 64],
            "object_ledger_count": 0,
            "object_ledger_digest": "e" * 64,
            "content_ledger_count": 1,
            "content_ledger_digest": "1" * 64,
        }],
    )
    archive = SimpleNamespace(pk=artifact_id)
    detailed_manifest = {
        "format": "spaceworks-phase5a-v3",
        "snapshot_at": "2026-08-24T00:00:00+00:00",
        "build": {"source_hash": SOURCE_HASH},
        "oci_digest": "sha256:" + "9" * 64,
        "postgres": {
            "source_server_major": POSTGRES_MAJOR,
            "client": f"pg_dump (PostgreSQL) {POSTGRES_MAJOR}.4",
            "supported_source_majors": list(SUPPORTED_SOURCE_MAJORS),
        },
        "recipient_fingerprints": [],
        "storage": {"objects": []},
        "contents": [
            {
                "path": "database.dump", "size": len(database),
                "sha256": hashlib.sha256(database).hexdigest(),
            },
            {
                "path": "keys/env.json", "size": 1, "sha256": "d" * 64,
            },
        ],
    }
    bind_source_partition_proof(capture, archive, detailed_manifest, root)
    manifest = outer_manifest.build_outer_manifest(
        archive=archive,
        capture=capture,
        detailed_manifest=detailed_manifest,
        root=root,
    )
    fixture = ImportFixture(
        root=root,
        encrypted=encrypted,
        bundle=bundle,
        manifest_file=manifest_file,
        secrets_file=secrets_file,
        manifest=manifest,
        secrets={name: f"value-for-{name}" for name in CONTINUITY_KEYS},
        members={
            "database.dump": database,
            slice_path: slice_bytes,
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
