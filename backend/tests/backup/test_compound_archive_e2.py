from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from types import SimpleNamespace
import uuid

import pytest
from django.utils import timezone

from apps.backup import archive_builder, archive_payload, compound_archive
from apps.backup.models import (
    BackupArchive,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
)
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.recipients import fingerprint_for
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)

PLATFORM_RECIPIENT = "age1platform-e2"
TENANT_RECIPIENT_ONE = "age1tenant-e2-one"
TENANT_RECIPIENT_TWO = "age1tenant-e2-two"
FULL_MAIN_BYTES = b"full deployment with sovereign tenant content marker"
PROJECTED_MAIN_BYTES = b"verified readable main without sovereign rows"


def _archive():
    return BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )


def _recipient(makerspace, value, label):
    return MakerspaceArchiveRecipient.objects.create(
        makerspace=makerspace,
        public_recipient=value,
        fingerprint=fingerprint_for(value),
        label=label,
        verified_at=timezone.now(),
    )


def _prepare_build(monkeypatch, settings, markers):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    monkeypatch.setattr(archive_builder, "_require_binary", lambda _command: None)
    monkeypatch.setattr(
        archive_builder,
        "_storage_modes",
        lambda: {"private": "versioned", "public_image": "versioned"},
    )
    monkeypatch.setattr(
        archive_payload,
        "_pg_dump",
        lambda path, _snapshot: path.write_bytes(FULL_MAIN_BYTES),
    )
    monkeypatch.setattr(
        archive_payload,
        "_object_closure",
        lambda: {"private": {}, "public_image": {}},
    )
    monkeypatch.setattr(
        archive_payload, "_write_continuity_keys", lambda _path: None
    )
    monkeypatch.setattr(
        archive_payload, "_command_version", lambda _command: "pg_dump 16"
    )
    monkeypatch.setattr(
        compound_archive, "verify_unsealed_slice", lambda *_args, **_kwargs: None
    )
    def project_main(source, destination, makerspace_ids, _expected):
        if makerspace_ids:
            destination.write_bytes(PROJECTED_MAIN_BYTES)
        else:
            shutil.copyfile(source, destination)

    monkeypatch.setattr(
        compound_archive, "project_readable_main_dump", project_main
    )

    def tenant_payload(makerspace_id, root):
        root.mkdir(parents=True)
        (root / "payload.json").write_text(
            markers[makerspace_id], encoding="utf-8"
        )
        return {"private": {}, "public_image": {}}

    monkeypatch.setattr(archive_payload, "_tenant_payload", tenant_payload)
    commands = []

    def fake_age(command, **_kwargs):
        commands.append(command)
        output = Path(command[command.index("-o") + 1])
        payload = _kwargs.get("input")
        if payload is None:
            shutil.copyfile(command[-1], output)
        else:
            output.write_bytes(b"sealed:" + hashlib.sha256(payload).digest())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(archive_builder.subprocess, "run", fake_age)
    return commands


def _command_recipients(command):
    return [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "-r"
    ]


def test_deployment_compound_has_only_off_slice_and_sanitized_root_manifest(
    monkeypatch, settings
):
    sovereign = Makerspace.objects.create(
        name="Sovereign private name",
        slug="sovereign-private-slug",
        superadmin_access_enabled=False,
    )
    accessible = Makerspace.objects.create(
        name="Platform accessible",
        slug="platform-accessible",
        superadmin_access_enabled=True,
    )
    _recipient(sovereign, TENANT_RECIPIENT_ONE, "Tenant key one")
    _recipient(sovereign, TENANT_RECIPIENT_TWO, "Tenant key two")
    _recipient(accessible, "age1accessible-e2", "Accessible tenant key")
    MakerspaceArchiveCustodyState.objects.create(
        makerspace=sovereign,
        state=MakerspaceArchiveCustodyState.State.HEALTHY,
    )
    markers = {
        sovereign.pk: "sovereign tenant content marker",
        accessible.pk: "accessible tenant content marker",
    }
    commands = _prepare_build(monkeypatch, settings, markers)

    encrypted, manifest, tempdir, _digest = archive_builder.build_archive(
        _archive()
    )
    try:
        assert manifest["format"] == "spaceworks-phase5a-v3"
        assert len(manifest["slices"]) == 1
        slice_entry = manifest["slices"][0]
        assert slice_entry["makerspace_id"] == sovereign.pk
        assert slice_entry["recipient_fingerprints"] == sorted([
            fingerprint_for(TENANT_RECIPIENT_ONE),
            fingerprint_for(TENANT_RECIPIENT_TWO),
        ])
        assert slice_entry["custody_state"] == "healthy"
        assert "recipients" not in manifest
        assert manifest["recipient_fingerprints"] == [
            fingerprint_for(PLATFORM_RECIPIENT)
        ]

        manifest_text = json.dumps(manifest, sort_keys=True)
        assert "public_recipient" not in manifest_text
        assert '"label"' not in manifest_text
        for forbidden in (
            PLATFORM_RECIPIENT,
            TENANT_RECIPIENT_ONE,
            TENANT_RECIPIENT_TWO,
            "age1accessible-e2",
            "Tenant key one",
            "Tenant key two",
            "Accessible tenant key",
            "Sovereign private name",
            "sovereign tenant content marker",
        ):
            assert forbidden not in manifest_text

        root = Path(tempdir.name, "bundle")
        slice_path = root / slice_entry["path"]
        assert slice_entry["size_bytes"] == slice_path.stat().st_size
        assert slice_entry["ciphertext_sha256"] == hashlib.sha256(
            slice_path.read_bytes()
        ).hexdigest()
        assert (root / "database.dump").read_bytes() == PROJECTED_MAIN_BYTES
        assert not (root / "main").exists()
        assert [
            entry["path"] for entry in manifest["contents"]
        ] == ["database.dump", slice_entry["path"]]
        with tarfile.open(slice_path) as sealed_slice:
            payload = sealed_slice.extractfile("./rows/payload.json")
            assert payload is not None
            assert payload.read().decode() == markers[sovereign.pk]

        assert _command_recipients(commands[0]) == [
            TENANT_RECIPIENT_ONE,
            TENANT_RECIPIENT_TWO,
        ]
        assert PLATFORM_RECIPIENT not in _command_recipients(commands[0])
        assert _command_recipients(commands[-1]) == [PLATFORM_RECIPIENT]
        assert encrypted.exists()
    finally:
        tempdir.cleanup()


@pytest.mark.parametrize("with_slices", (False, True))
def test_extracted_deployment_payload_stays_at_archive_root(
    monkeypatch, settings, tmp_path, with_slices
):
    markers = {}
    if with_slices:
        sovereign = Makerspace.objects.create(
            name="Root layout sovereign",
            slug="root-layout-sovereign",
            superadmin_access_enabled=False,
        )
        _recipient(sovereign, TENANT_RECIPIENT_ONE, "Tenant key one")
        _recipient(sovereign, TENANT_RECIPIENT_TWO, "Tenant key two")
        MakerspaceArchiveCustodyState.objects.create(
            makerspace=sovereign,
            state=MakerspaceArchiveCustodyState.State.HEALTHY,
        )
        markers[sovereign.pk] = "sealed tenant content"
    _prepare_build(monkeypatch, settings, markers)

    encrypted, _manifest, tempdir, _digest = archive_builder.build_archive(
        _archive()
    )
    extracted = tmp_path / "extracted"
    try:
        with tarfile.open(encrypted) as bundle:
            bundle.extractall(extracted, filter="data")

        root_manifest = extracted / "manifest.json"
        root_database = extracted / "database.dump"
        assert root_manifest.is_file()
        assert root_database.is_file()
        assert root_manifest.stat().st_size > 0
        assert root_database.stat().st_size > 0
        expected = PROJECTED_MAIN_BYTES if with_slices else FULL_MAIN_BYTES
        assert root_database.read_bytes() == expected
        assert not (extracted / "main").exists()
        assert len(list(extracted.rglob("manifest.json"))) == 1
        manifest = json.loads(root_manifest.read_text(encoding="utf-8"))
        assert bool(manifest["slices"]) is with_slices
        assert (extracted / "slices").is_dir() is with_slices
    finally:
        tempdir.cleanup()


def test_zero_valid_recipients_fails_the_deployment_run(monkeypatch, settings):
    sovereign = Makerspace.objects.create(
        name="No custody",
        slug="no-custody",
        superadmin_access_enabled=False,
    )
    markers = {sovereign.pk: "must never be sealed to nobody"}
    commands = _prepare_build(monkeypatch, settings, markers)

    with pytest.raises(BackupBuildError, match="no valid archive recipient"):
        archive_builder.build_archive(_archive())

    assert commands == []


def test_one_recipient_succeeds_with_degraded_custody_recorded(
    monkeypatch, settings
):
    sovereign = Makerspace.objects.create(
        name="Degraded custody",
        slug="degraded-custody",
        superadmin_access_enabled=False,
    )
    _recipient(sovereign, TENANT_RECIPIENT_ONE, "Only tenant key")
    MakerspaceArchiveCustodyState.objects.create(
        makerspace=sovereign,
        state=(
            MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT
        ),
    )
    commands = _prepare_build(
        monkeypatch,
        settings,
        {sovereign.pk: "degraded tenant content"},
    )

    _encrypted, manifest, tempdir, _digest = archive_builder.build_archive(
        _archive()
    )
    try:
        assert manifest["slices"][0]["custody_state"] == (
            MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT
        )
        assert manifest["slices"][0]["recipient_fingerprints"] == [
            fingerprint_for(TENANT_RECIPIENT_ONE)
        ]
        assert _command_recipients(commands[0]) == [TENANT_RECIPIENT_ONE]
    finally:
        tempdir.cleanup()
