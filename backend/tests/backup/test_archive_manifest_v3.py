from datetime import timedelta
import hashlib
import json
from pathlib import Path
import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.backup import archive_payload, storage
from apps.backup.archive_payload import _build_info
from apps.backup.digests import SUPPORTED_ARCHIVE_FORMATS
from apps.backup.management.commands.backup_control import Command
from apps.backup.models import BackupArchive, RestoreOperation
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)


def _restore():
    actor = User.objects.create_superuser(
        username=f"manifest-v3-{uuid.uuid4()}", password="secret"
    )
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=actor,
        status=BackupArchive.Status.AVAILABLE,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        age_encrypted=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    return RestoreOperation.objects.create(
        archive=archive,
        kind=RestoreOperation.Kind.ROLLBACK_IN_PLACE,
        requested_by=actor,
        stage=RestoreOperation.Stage.CLAIMED,
    )


def _manifest(restore, format_name, contents=None):
    value = {
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
        value["contents"] = contents
    return value


def _permit_remaining_preflight(monkeypatch, settings, tmp_path):
    settings.BACKUP_OPS_DIR = tmp_path
    monkeypatch.setattr(
        Command, "_check_setting_policies", staticmethod(lambda _archived: None)
    )
    monkeypatch.setattr(
        "apps.backup.management.commands.backup_control.shutil.which",
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
        "apps.backup.management.commands.backup_control.connections",
        {"default": Connection()},
    )

    class Client:
        def head_bucket(self, **_kwargs):
            return {}

    monkeypatch.setattr(storage, "client", lambda: Client())


def test_deployment_snapshot_manifest_is_v3_with_integer_coverage(
    monkeypatch, tmp_path
):
    first = Makerspace.objects.create(name="Covered one", slug="covered-one")
    second = Makerspace.objects.create(name="Covered two", slug="covered-two")
    # Deliberately superseded by Lane E: this used to assert that an archived
    # makerspace was NOT covered. The retained population is now every row in
    # makerspaces_makerspace in the exported snapshot, regardless of lifecycle
    # state or archived_at, because the dump physically contains its rows.
    # Servability controls traffic, not whether retained custody data needs
    # backup -- and the readable-main and sovereign sets must be exhaustive over
    # that population, or an archived sovereign tenant belongs to neither set
    # while its data still ships.
    archived = Makerspace.objects.create(
        name="Archived", slug="covered-archived", archived_at=timezone.now()
    )
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )
    selected = [{"label": "Platform", "public_recipient": "age1platform"}]

    monkeypatch.setattr(
        archive_payload,
        "_pg_dump",
        lambda path, _snapshot: path.write_bytes(b"database"),
    )
    monkeypatch.setattr(
        archive_payload, "_object_closure", lambda: {"private": {}, "public_image": {}}
    )
    monkeypatch.setattr(archive_payload, "_capture_objects", lambda *_args: [])
    monkeypatch.setattr(archive_payload, "_command_version", lambda _command: "pg_dump 16")

    manifest = archive_payload._snapshot_payload(
        archive,
        tmp_path,
        {"private": "versioned", "public_image": "versioned"},
        selected,
    )

    assert manifest["format"] == "spaceworks-phase5a-v3"
    assert manifest["recipients"] is selected
    assert manifest["covered_makerspace_ids"] == [first.pk, second.pk, archived.pk]
    assert all(type(value) is int for value in manifest["covered_makerspace_ids"])
    assert manifest["excluded_makerspace_ids"] == []
    assert manifest["partial"] is False
    assert "spaceworks-phase5a-v3" in SUPPORTED_ARCHIVE_FORMATS


def test_v3_preflight_refuses_missing_content_ledger(tmp_path):
    restore = _restore()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest(restore, "spaceworks-phase5a-v3")), encoding="utf-8"
    )

    with pytest.raises(CommandError, match="ledger is required"):
        call_command(
            "backup_control", "preflight", str(restore.pk),
            "--manifest", str(manifest_path), "--bundle", str(tmp_path),
        )


def test_legacy_preflight_refuses_compound_readable_main(tmp_path):
    restore = _restore()
    manifest = _manifest(restore, "spaceworks-phase5a-v3", contents=[])
    manifest["partial"] = True
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CommandError, match="legacy restore path"):
        call_command(
            "backup_control", "preflight", str(restore.pk),
            "--manifest", str(manifest_path), "--bundle", str(tmp_path),
        )


@pytest.mark.parametrize(
    "format_name", ("spaceworks-phase5a-v2", "spaceworks-phase5a-v3")
)
def test_v2_and_v3_preflight_accept_valid_content_ledgers(
    monkeypatch, settings, tmp_path, format_name
):
    restore = _restore()
    payload = tmp_path / "database.dump"
    payload.write_bytes(b"database")
    contents = [{
        "path": payload.name,
        "size": payload.stat().st_size,
        "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
    }]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest(restore, format_name, contents)), encoding="utf-8"
    )
    _permit_remaining_preflight(monkeypatch, settings, tmp_path)

    call_command(
        "backup_control", "preflight", str(restore.pk),
        "--manifest", str(manifest_path), "--bundle", str(tmp_path),
    )

    restore.refresh_from_db()
    assert restore.stage == RestoreOperation.Stage.PREFLIGHT
