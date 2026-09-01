from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import uuid

import pytest
from django.utils import timezone

from apps.backup import archive_builder, host_marker, producer_capability, storage
from apps.backup.host_marker import MarkerError
from apps.backup.models import BackupArchive, BackupArtifactLedger
from apps.ed25519 import encode_key, generate_keypair
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)


def _deployment_archive():
    return BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )


def _rewrite(installation, mutate):
    payload = json.loads(json.dumps(installation["payload"]))
    mutate(payload)
    installation["marker"].chmod(0o644)
    installation["marker"].write_text(json.dumps(payload), encoding="utf-8")
    installation["marker"].chmod(0o444)


def _apply_refusal(case, installation, monkeypatch):
    if case == "absent":
        installation["marker"].unlink()
    elif case == "non_root_owned":

        def reject(_path):
            raise MarkerError("Host marker and directory must be root-owned.")

        monkeypatch.setattr(producer_capability, "_assert_trusted_file", reject)
    elif case == "wrong_mode":
        installation["marker"].chmod(0o644)
    elif case == "unreadable":
        original = Path.read_text

        def unreadable(path, *args, **kwargs):
            if path == installation["marker"]:
                raise PermissionError("refused")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", unreadable)
    elif case == "unparseable":
        installation["marker"].chmod(0o644)
        installation["marker"].write_text("{", encoding="utf-8")
        installation["marker"].chmod(0o444)
    elif case == "script_hash":
        (installation["scripts"] / "restore.sh").write_bytes(b"modified\n")
    elif case == "entrypoint_hash":
        installation["entrypoint"].write_bytes(b"modified\n")
    elif case == "protocol_range":
        _rewrite(installation, lambda value: value.update({
            "compound_protocol": {
                "minimum": "spaceworks-lane-e-b1-v2",
                "maximum": "spaceworks-lane-e-b1-v3",
            }
        }))
    elif case == "signing_fingerprint":
        _rewrite(installation, lambda value: value.update({
            "signing_key_fingerprint": "0" * 64
        }))
    elif case == "migration_version":
        _rewrite(installation, lambda value: value.update({
            "migration_version": "django-migrations-v1:" + "0" * 64
        }))


@pytest.mark.parametrize(
    ("case", "reason"),
    (
        ("absent", "producer-capability-marker-absent"),
        ("non_root_owned", "producer-capability-marker-ownership"),
        ("wrong_mode", "producer-capability-marker-mode"),
        ("unreadable", "producer-capability-marker-unreadable"),
        ("unparseable", "producer-capability-marker-malformed"),
        ("script_hash", "producer-capability-privileged-script-hash"),
        ("entrypoint_hash", "producer-capability-entrypoint-hash"),
        ("protocol_range", "producer-capability-protocol-range"),
        ("signing_fingerprint", "producer-capability-signing-fingerprint"),
        ("migration_version", "producer-capability-migration-version"),
    ),
)
def test_every_refusal_precedes_artifact_staging_and_ledger(
    case, reason, installed_producer_capability, monkeypatch, tmp_path
):
    installation = installed_producer_capability
    _apply_refusal(case, installation, monkeypatch)
    tempdirs = []
    original = archive_builder.tempfile.TemporaryDirectory

    def tracked_tempdir(*args, **kwargs):
        kwargs["dir"] = tmp_path
        result = original(*args, **kwargs)
        tempdirs.append(Path(result.name))
        return result

    staged_objects = set()
    monkeypatch.setattr(
        archive_builder.tempfile, "TemporaryDirectory", tracked_tempdir
    )
    monkeypatch.setattr(
        storage, "upload_staging",
        lambda key, _path: staged_objects.add(key),
    )
    archive = _deployment_archive()

    with pytest.raises(
        producer_capability.ProducerCapabilityRefused, match=reason
    ) as refused:
        archive_builder.build_archive(archive)

    assert refused.value.reason == reason
    assert tempdirs == []
    assert not list(tmp_path.rglob("*.tar.age"))
    assert staged_objects == set()
    assert not BackupArtifactLedger.objects.filter(artifact_id=archive.pk).exists()


def test_single_byte_local_script_modification_invalidates_gate(
    installed_producer_capability
):
    script = installed_producer_capability["scripts"] / "restore.sh"
    script.write_bytes(script.read_bytes() + b"x")

    with pytest.raises(
        producer_capability.ProducerCapabilityRefused,
        match="producer-capability-privileged-script-hash",
    ):
        producer_capability.assert_producer_capability()


def test_script_rollback_invalidates_gate(installed_producer_capability):
    script = installed_producer_capability["scripts"] / "import-backup.sh"
    script.write_bytes(b"#!/usr/bin/env bash\n# older restore supervisor\n")

    with pytest.raises(
        producer_capability.ProducerCapabilityRefused,
        match="producer-capability-privileged-script-hash",
    ):
        producer_capability.assert_producer_capability()


def test_matching_versions_cannot_override_real_hash_mismatch(
    installed_producer_capability
):
    installation = installed_producer_capability
    assert installation["payload"]["version"] == producer_capability.MARKER_VERSION
    assert installation["payload"]["compound_protocol"]["minimum"].endswith("v1")
    (installation["scripts"] / "host-capability.py").write_bytes(b"older bytes\n")

    with pytest.raises(
        producer_capability.ProducerCapabilityRefused,
        match="producer-capability-privileged-script-hash",
    ):
        producer_capability.assert_producer_capability()


def test_shared_trusted_file_check_rejects_non_root_marker(
    installed_producer_capability, monkeypatch
):
    marker = installed_producer_capability["marker"]
    original = Path.stat

    def fake_stat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == marker:
            values = list(result)
            values[4] = 10001
            return os.stat_result(values)
        if path == marker.parent:
            values = list(result)
            values[4] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)
    monkeypatch.setattr(
        producer_capability, "_assert_trusted_file", host_marker._assert_trusted_file
    )

    with pytest.raises(
        producer_capability.ProducerCapabilityRefused,
        match="producer-capability-marker-ownership",
    ):
        producer_capability.read_capability_marker(marker)


def test_private_signer_must_match_host_verification_identity(
    installed_producer_capability, settings
):
    private, _public = generate_keypair()
    settings.BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY = encode_key(private)

    with pytest.raises(
        producer_capability.ProducerCapabilityRefused,
        match="producer-capability-signing-fingerprint",
    ) as refused:
        producer_capability.assert_producer_capability()

    detail = str(refused.value)
    assert settings.BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY not in detail
    assert settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY not in detail


def test_non_compound_backup_succeeds_without_capability_marker(
    installed_producer_capability, monkeypatch
):
    installed_producer_capability["marker"].unlink()
    makerspace = Makerspace.objects.create(name="Single archive", slug="single-archive")
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.MAKERSPACE,
        makerspace=makerspace,
        superadmin_access_at_decision=True,
        object_key=f"backup-archives/makerspace/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )
    selected = [{"label": "single", "public_recipient": "age1single"}]
    monkeypatch.setattr(archive_builder.recipients, "selection_for", lambda _archive: selected)
    monkeypatch.setattr(archive_builder, "_selection_at_read_committed", lambda _archive: selected)
    monkeypatch.setattr(archive_builder, "_require_binary", lambda _command: None)
    monkeypatch.setattr(archive_builder, "_storage_modes", lambda: {})

    def snapshot(_archive, root, _modes, _selected):
        (root / "database.dump").write_bytes(b"ordinary backup")
        return {"format": "spaceworks-phase5a-v3", "storage": {"objects": []}}

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
        shutil.copyfile(command[-1], command[command.index("-o") + 1])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(archive_builder, "_snapshot_payload", snapshot)
    monkeypatch.setattr(archive_builder.subprocess, "run", encrypt)

    result = archive_builder.build_archive(archive)
    try:
        assert result.encrypted.is_file()
    finally:
        result.tempdir.cleanup()
