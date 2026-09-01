from datetime import timedelta
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.backup import archive_builder, storage
from apps.backup.archive_payload import _build_info
from apps.backup.archive_import import import_disaster_archive
from apps.backup.management.commands.backup_control import Command
from apps.backup.models import BackupArchive, RestoreOperation
from apps.makerspaces.models import Makerspace


def _restore(stage=RestoreOperation.Stage.CLAIMED, *, archive_sha256=""):
    actor = User.objects.create_superuser(
        username=f"digest-{uuid.uuid4()}", password="secret"
    )
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=actor,
        status=BackupArchive.Status.AVAILABLE,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        archive_sha256=archive_sha256,
        age_encrypted=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    restore = RestoreOperation.objects.create(
        archive=archive,
        kind=RestoreOperation.Kind.ROLLBACK_IN_PLACE,
        requested_by=actor,
        stage=stage,
    )
    return actor, restore


def _manifest(restore, *, format_name="spaceworks-phase5a-v2", contents=None):
    manifest = {
        "format": format_name,
        "archive_id": str(restore.archive_id),
        "scope": BackupArchive.Scope.DEPLOYMENT,
        "age_encrypted": True,
        "postgres": {"source_server_major": 14},
        # The running build identity, not a literal: "unknown" is only correct
        # outside an image, so hard-coding it made this pass on the host and
        # fail in Docker, where /app/BUILD_INFO.json carries a real hash.
        "build": {"source_hash": _build_info()["source_hash"]},
        "settings": {},
    }
    if contents is not None:
        manifest["contents"] = contents
    return manifest


@pytest.mark.django_db
def test_built_archive_manifest_contains_streamed_content_ledger(
    monkeypatch, settings
):
    settings.BACKUP_AGE_RECIPIENT = "age1test"
    monkeypatch.setattr(archive_builder, "_require_binary", lambda _command: None)
    monkeypatch.setattr(
        archive_builder,
        "_storage_modes",
        lambda: {"private": "versioned", "public_image": "versioned"},
    )
    selected = [{"label": "Compatibility", "public_recipient": "age1test"}]
    monkeypatch.setattr(
        archive_builder.recipients, "selection_for", lambda _archive: selected
    )
    monkeypatch.setattr(
        archive_builder, "_selection_at_read_committed", lambda _archive: selected
    )

    def snapshot(_archive, root, _modes, selected_recipients):
        assert selected_recipients is selected
        (root / "database.dump").write_bytes(b"database bytes")
        objects = archive_builder._capture_objects(
            root / "objects",
            {
                "private": {
                    "photo.jpg": {"makerspace_id": 1, "module_key": "events"}
                },
                "public_image": {},
            },
            _modes,
        )
        return {
            "format": "spaceworks-phase5a-v2",
            "recipients": selected_recipients,
            "storage": {"objects": objects},
        }

    real_run = archive_builder.subprocess.run

    def encrypt(command, **_kwargs):
        if "-o" not in command:
        # Not an age invocation. This fake replaces the SHARED subprocess module, so
        # every other binary the code runs lands here too -- including
        # `postgres_client._binary_major`'s `<client> --version` probe. Delegate
        # instead of stubbing: a bare SimpleNamespace has no `.stdout`, which turned a
        # clean PostgresClientUnavailable into an AttributeError on every host without
        # a versioned client directory (any non-Debian/RHEL host).
            return real_run(command, **_kwargs)
        output = Path(command[command.index("-o") + 1])
        shutil.copyfile(command[-1], output)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(archive_builder, "_snapshot_payload", snapshot)
    monkeypatch.setattr(archive_builder.subprocess, "run", encrypt)

    class Client:
        def head_object(self, **_kwargs):
            return {"VersionId": "captured-version"}

        def get_object(self, **_kwargs):
            return {"Body": BytesIO(b"object bytes"), "Metadata": {}}

    monkeypatch.setattr(archive_builder.storage, "client", lambda: Client())

    makerspace = Makerspace.objects.create(
        name="Digest ledger makerspace", slug=f"digest-ledger-{uuid.uuid4().hex}"
    )
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.MAKERSPACE,
        makerspace=makerspace,
        superadmin_access_at_decision=True,
        object_key=f"backup-archives/makerspace/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )
    encrypted, manifest, tempdir, archive_sha256 = archive_builder.build_archive(
        archive
    )
    try:
        root = Path(tempdir.name, "bundle")
        assert [entry["path"] for entry in manifest["contents"]] == [
            "database.dump",
            "objects/private/photo.jpg",
        ]
        for entry in manifest["contents"]:
            content = (root / entry["path"]).read_bytes()
            assert entry["size"] == len(content)
            assert entry["sha256"] == hashlib.sha256(content).hexdigest()
        assert "manifest.json" not in {entry["path"] for entry in manifest["contents"]}
        captured = manifest["storage"]["objects"][0]
        assert captured["sha256"] == hashlib.sha256(b"object bytes").hexdigest()
        assert archive_sha256 == hashlib.sha256(encrypted.read_bytes()).hexdigest()
    finally:
        tempdir.cleanup()


@pytest.mark.django_db
def test_preflight_rejects_altered_declared_bundle_file(tmp_path):
    _actor, restore = _restore()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    database = bundle / "database.dump"
    database.write_bytes(b"original")
    contents = [{
        "path": "database.dump",
        "size": len(b"original"),
        "sha256": hashlib.sha256(b"original").hexdigest(),
    }]
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(restore, contents=contents)))
    database.write_bytes(b"altered")

    with pytest.raises(CommandError, match="database.dump"):
        call_command(
            "backup_control",
            "preflight",
            str(restore.pk),
            "--manifest",
            str(manifest_path),
            "--bundle",
            str(bundle),
        )


@pytest.mark.django_db
def test_preflight_accepts_v1_manifest_without_content_ledger(
    monkeypatch, settings, tmp_path
):
    _actor, restore = _restore()
    settings.BACKUP_OPS_DIR = tmp_path
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(
        restore, format_name="spaceworks-phase5a-v1"
    )))
    monkeypatch.setattr(
        Command, "_check_setting_policies", staticmethod(lambda _archived: None)
    )
    monkeypatch.setattr(
        "apps.backup.backup_control_preflight.shutil.which",
        lambda _command: "/usr/bin/tool",
    )

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query):
            assert query == "SHOW server_version_num"

        def fetchone(self):
            return (160000,)

    class Connection:
        def cursor(self):
            return Cursor()

    monkeypatch.setattr(
        "apps.backup.backup_control_preflight.connections",
        {"default": Connection()},
    )

    class Client:
        def head_bucket(self, **_kwargs):
            return {}

    monkeypatch.setattr(storage, "client", lambda: Client())
    output = StringIO()

    call_command(
        "backup_control",
        "preflight",
        str(restore.pk),
        "--manifest",
        str(manifest_path),
        "--bundle",
        str(tmp_path),
        stdout=output,
    )

    restore.refresh_from_db()
    assert restore.stage == RestoreOperation.Stage.PREFLIGHT
    assert "preflight-ok" in output.getvalue()


@pytest.mark.django_db
def test_export_archive_removes_output_when_stored_digest_does_not_match(
    monkeypatch, tmp_path
):
    expected = hashlib.sha256(b"original archive").hexdigest()
    _actor, restore = _restore(archive_sha256=expected)
    monkeypatch.setattr(storage, "open_archive", lambda _key: BytesIO(b"altered archive"))
    output = tmp_path / "exported.tar.age"

    with pytest.raises(CommandError, match="stored digest"):
        call_command(
            "backup_control",
            "export-archive",
            str(restore.pk),
            "--output",
            str(output),
        )

    assert not output.exists()


@pytest.mark.django_db
def test_import_rejects_mismatched_expected_digest_before_storage(
    monkeypatch, tmp_path
):
    actor = User.objects.create_superuser(username="digest-import", password="secret")
    encrypted = tmp_path / "archive.tar.age"
    encrypted.write_bytes(b"encrypted archive")
    manifest = {
        "format": "spaceworks-phase5a-v2",
        "archive_id": str(uuid.uuid4()),
        "scope": BackupArchive.Scope.DEPLOYMENT,
        "age_encrypted": True,
    }
    uploads = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: uploads.append(args))

    with pytest.raises(ValidationError, match="expected digest"):
        import_disaster_archive(
            actor, encrypted, manifest, expected_sha256="0" * 64
        )

    assert uploads == []
    assert BackupArchive.objects.count() == 0
    assert RestoreOperation.objects.count() == 0
