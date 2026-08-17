import base64
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest

from apps.backup.digests import (
    SUPPORTED_ARCHIVE_FORMATS,
    sha256_bytes,
    sha256_file,
)
from apps.data_export import runner as data_export_runner
from apps.encryption import services
from apps.encryption.cache import dek_cache_disabled
from apps.encryption.models import MakerspaceEncryptionKey
from apps.encryption.services import disable_dek, get_or_create_active_dek, rotate_dek
from apps.makerspaces.models import Makerspace
from apps.tenant_migration import archive_envelope
from apps.tenant_migration.keys import collect_source_keys
from apps.tenant_migration.preflight import SourcePreflightResult
from tests.encryption.conftest import enabled_encryption


@pytest.mark.django_db
def test_active_and_rotated_keys_are_carried_but_disabled_is_metadata_only():
    space = Makerspace.objects.create(name="Key Carry", slug="key-carry")
    with enabled_encryption():
        first = get_or_create_active_dek(space.pk)
        second = rotate_dek(space.pk)
        third = rotate_dek(space.pk)
        disable_dek(space.pk, first.key.version)

        records = collect_source_keys(space)

    by_version = {record["version"]: record for record in records}
    assert by_version[1] == {
        "version": 1,
        "status": MakerspaceEncryptionKey.Status.DISABLED,
        "metadata_only": True,
        "insert_at_target": False,
    }
    assert by_version[2]["status"] == MakerspaceEncryptionKey.Status.ROTATED
    assert by_version[2]["dek"] == second.dek
    assert by_version[3]["status"] == MakerspaceEncryptionKey.Status.ACTIVE
    assert by_version[3]["dek"] == third.dek


@pytest.mark.django_db
def test_sensitive_scope_bypasses_and_clears_the_process_cache():
    space = Makerspace.objects.create(name="No Key Cache", slug="no-key-cache")
    with enabled_encryption():
        get_or_create_active_dek(space.pk)
        with dek_cache_disabled(), patch.object(
            services,
            "broker_for_backend",
            wraps=services.broker_for_backend,
        ) as broker_for_backend:
            collect_source_keys(space)
            collect_source_keys(space)
        assert broker_for_backend.call_count == 2


def test_archive_stream_is_age_output_with_matching_in_memory_ledger(
    monkeypatch, settings, tmp_path
):
    settings.BACKUP_AGE_RECIPIENT = "age1recipient"
    monkeypatch.chdir(tmp_path)
    # Globbing tmp_path alone cannot show this: the export runner builds its tree in a
    # `tempfile.TemporaryDirectory` under the SYSTEM temp dir, so a plaintext ZIP would
    # land nowhere this test looks. Carried DEKs must never reach disk unencrypted, so
    # forbid the packaging call outright rather than inspecting one directory for it.
    def _forbidden_make_archive(*args, **kwargs):
        raise AssertionError(
            "the migration export must never write a plaintext archive to disk"
        )

    monkeypatch.setattr(
        data_export_runner.shutil, "make_archive", _forbidden_make_archive
    )
    source = tempfile.TemporaryDirectory(dir=tmp_path)
    root = Path(source.name, "archive")
    root.mkdir()
    (root / "tenant.csv").write_bytes(b"id,name\n1,Lathe\n")
    export_manifest = {"snapshot_at": "2026-08-16T00:00:00+00:00"}
    tempdir = SimpleNamespace(cleanup=source.cleanup)
    space = SimpleNamespace(pk=17, id=17, slug="source-space", name="Source Space")
    preflight = SourcePreflightResult(
        makerspace_id=17,
        storage_mode={"private": "versioned", "public_image": "quiesced"},
        carried_key_versions=((1, "active"), (2, "disabled")),
    )
    monkeypatch.setattr(archive_envelope, "_require_binary", lambda _command: None)
    monkeypatch.setattr(
        archive_envelope, "run_source_preflight", lambda _space: preflight
    )
    monkeypatch.setattr(
        archive_envelope,
        "collect_source_keys",
        lambda _space: [
            {"version": 1, "status": "active", "dek": b"d" * 32},
            {
                "version": 2,
                "status": "disabled",
                "metadata_only": True,
                "insert_at_target": False,
            },
        ],
    )
    monkeypatch.setattr(
        archive_envelope,
        "build_archive",
        lambda _job, **_kwargs: (root, export_manifest, tempdir),
    )
    gate_owner = uuid.uuid4()

    @contextmanager
    def quiesced(_space, _actor, **_kwargs):
        yield SimpleNamespace(owner_id=gate_owner, fencing_token=7)

    monkeypatch.setattr(archive_envelope, "quiesced_snapshot", quiesced)

    captured = {}

    class NonClosingBytesIO(io.BytesIO):
        def close(self):
            pass

    class FakeAge:
        def __init__(self, command, **_kwargs):
            self.command = command
            self.stdin = NonClosingBytesIO()
            self.stderr = io.BytesIO()
            self.returncode = None
            captured["process"] = self

        def poll(self):
            return self.returncode

        def wait(self):
            self.returncode = 0
            output = Path(self.command[self.command.index("-o") + 1])
            output.write_bytes(b"age-encrypted-test-envelope")
            return 0

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(archive_envelope.subprocess, "Popen", FakeAge)
    output = tmp_path / "tenant-migration.tar.age"

    path, manifest, archive_digest = archive_envelope.build_tenant_migration_archive(
        space, output
    )

    assert path.read_bytes() == b"age-encrypted-test-envelope"
    assert archive_digest == sha256_file(path)
    assert manifest["format"] == archive_envelope.FORMAT
    assert manifest["source"]["gate"] == {
        "owner_id": str(gate_owner),
        "fencing_token": 7,
    }
    assert manifest["format"] not in SUPPORTED_ARCHIVE_FORMATS
    assert captured["process"].command == [
        "age",
        "-r",
        "age1recipient",
        "-o",
        str(output),
    ]
    assert not list(tmp_path.glob("*.tar"))
    assert not list(tmp_path.glob("*.zip"))
    captured_tar = captured["process"].stdin.getvalue()
    with tarfile.open(fileobj=io.BytesIO(captured_tar), mode="r:") as bundle:
        members = {
            member.name: bundle.extractfile(member).read()
            for member in bundle.getmembers()
            if member.isfile()
        }
    keys = json.loads(members["keys/deks.json"])
    assert base64.b64decode(keys["keys"][0]["dek_base64"]) == b"d" * 32
    assert "dek_base64" not in keys["keys"][1]
    for entry in manifest["contents"]:
        assert len(members[entry["path"]]) == entry["size"]
        assert sha256_bytes(members[entry["path"]]) == entry["sha256"]
