from datetime import timedelta
from pathlib import Path
import shutil
from types import SimpleNamespace
import uuid

import pytest
from django.utils import timezone

from apps.backup import archive_builder, recipients
from apps.backup.models import BackupArchive, MakerspaceArchiveRecipient
from apps.backup.recipients import enroll_recipient
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)

VALID_RECIPIENT = (
    "age1qqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc0savhh7m"
)
PLATFORM_RECIPIENT = "age1platform-recipient"


def _archive(makerspace, *, decision=None, scope=BackupArchive.Scope.MAKERSPACE):
    return BackupArchive.objects.create(
        scope=scope,
        makerspace=makerspace if scope == BackupArchive.Scope.MAKERSPACE else None,
        superadmin_access_at_decision=decision,
        object_key=f"backup-archives/{scope}/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )


def _recipient(makerspace, *, verified=True, public_recipient=VALID_RECIPIENT):
    return MakerspaceArchiveRecipient.objects.create(
        makerspace=makerspace,
        public_recipient=public_recipient,
        fingerprint=uuid.uuid4().hex * 2,
        label="Tenant custody",
        verified_at=timezone.now() if verified else None,
    )


def _track_tempdirs(monkeypatch, tmp_path):
    original = archive_builder.tempfile.TemporaryDirectory
    paths = []

    def tracked(*args, **kwargs):
        kwargs["dir"] = tmp_path
        tempdir = original(*args, **kwargs)
        paths.append(Path(tempdir.name))
        return tempdir

    monkeypatch.setattr(archive_builder.tempfile, "TemporaryDirectory", tracked)
    return paths


def _successful_build_stubs(monkeypatch):
    monkeypatch.setattr(archive_builder, "_require_binary", lambda _command: None)
    monkeypatch.setattr(
        archive_builder,
        "_storage_modes",
        lambda: {"private": "versioned", "public_image": "versioned"},
    )

    def snapshot(_archive, root, _modes, selected):
        tenant = root / "tenant"
        tenant.mkdir()
        (tenant / "payload.json").write_text("plaintext", encoding="utf-8")
        return {
            "format": "spaceworks-phase5a-v3",
            "recipients": selected,
            "storage": {"objects": []},
        }

    monkeypatch.setattr(archive_builder, "_snapshot_payload", snapshot)
    calls = []

    def encrypt(args, **_kwargs):
        calls.append(args)
        shutil.copyfile(args[-1], args[args.index("-o") + 1])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(archive_builder.subprocess, "run", encrypt)
    return calls


def test_deployment_selection_is_platform_recipient_only(settings):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    archive = _archive(None, scope=BackupArchive.Scope.DEPLOYMENT)

    assert recipients.selection_for(archive) == [{
        "label": "Platform backup recipient",
        "public_recipient": PLATFORM_RECIPIENT,
    }]


def test_unverified_recipient_is_ignored_and_cannot_enable_build(
    monkeypatch, settings, tmp_path
):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    makerspace = Makerspace.objects.create(
        name="Unverified", slug="archive-unverified", superadmin_access_enabled=False
    )
    enroll_recipient(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="Not yet proved",
    )
    archive = _archive(makerspace)
    paths = _track_tempdirs(monkeypatch, tmp_path)

    with pytest.raises(archive_builder.BackupBuildError, match="verified"):
        archive_builder.build_archive(archive)

    assert paths == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("switch_enabled", "expected"),
    ((False, [VALID_RECIPIENT]), (True, [VALID_RECIPIENT, PLATFORM_RECIPIENT])),
)
def test_switch_controls_platform_recipient_in_manifest_and_age_argv(
    monkeypatch, settings, switch_enabled, expected
):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    makerspace = Makerspace.objects.create(
        name=f"Switch {switch_enabled}",
        slug=f"archive-switch-{switch_enabled}",
        superadmin_access_enabled=switch_enabled,
    )
    _recipient(makerspace)
    archive = _archive(makerspace)
    calls = _successful_build_stubs(monkeypatch)

    _encrypted, manifest, tempdir, _digest = archive_builder.build_archive(archive)
    try:
        assert [item["public_recipient"] for item in manifest["recipients"]] == expected
        argv_recipients = [
            calls[0][index + 1]
            for index, value in enumerate(calls[0])
            if value == "-r"
        ]
        assert argv_recipients == expected
    finally:
        tempdir.cleanup()


def test_frozen_switch_value_ignores_flipped_live_flag(settings):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    makerspace = Makerspace.objects.create(
        name="Frozen switch", slug="archive-frozen", superadmin_access_enabled=False
    )
    _recipient(makerspace)
    archive = _archive(makerspace, decision=True)

    assert len(recipients.selection_for(archive)) == 2

    archive.superadmin_access_at_decision = False
    archive.save(update_fields=("superadmin_access_at_decision",))
    makerspace.superadmin_access_enabled = True
    makerspace.save(update_fields=("superadmin_access_enabled",))
    assert recipients.selection_for(archive) == [{
        "label": "Tenant custody",
        "public_recipient": VALID_RECIPIENT,
    }]


@pytest.mark.parametrize("failure_at", ("mkdir", "storage", "payload"))
def test_every_build_failure_cleans_plaintext_workspace(
    monkeypatch, settings, tmp_path, failure_at
):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    makerspace = Makerspace.objects.create(
        name=f"Cleanup {failure_at}",
        slug=f"archive-cleanup-{failure_at}",
        superadmin_access_enabled=False,
    )
    _recipient(makerspace)
    archive = _archive(makerspace)
    paths = _track_tempdirs(monkeypatch, tmp_path)
    monkeypatch.setattr(archive_builder, "_require_binary", lambda _command: None)

    if failure_at == "mkdir":
        original_mkdir = Path.mkdir

        def fail_bundle_mkdir(path, *args, **kwargs):
            if path.name == "bundle":
                raise OSError("mkdir failed")
            return original_mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", fail_bundle_mkdir)
    elif failure_at == "storage":
        monkeypatch.setattr(
            archive_builder,
            "_storage_modes",
            lambda: (_ for _ in ()).throw(RuntimeError("storage failed")),
        )
    else:
        monkeypatch.setattr(
            archive_builder,
            "_storage_modes",
            lambda: {"private": "versioned", "public_image": "versioned"},
        )

        def fail_after_plaintext(_archive, root, _modes, _selected):
            tenant = root / "tenant"
            tenant.mkdir()
            (tenant / "payload.json").write_text("plaintext", encoding="utf-8")
            raise RuntimeError("payload failed")

        monkeypatch.setattr(archive_builder, "_snapshot_payload", fail_after_plaintext)

    expected = archive_builder.BackupBuildError if failure_at == "mkdir" else RuntimeError
    with pytest.raises(expected):
        archive_builder.build_archive(archive)

    assert paths and all(not path.exists() for path in paths)
    assert list(tmp_path.iterdir()) == []


def test_committed_revoke_after_manifest_write_aborts_before_age(
    monkeypatch, settings, tmp_path
):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    makerspace = Makerspace.objects.create(
        name="Urgent revoke", slug="archive-urgent-revoke",
        superadmin_access_enabled=False,
    )
    recipient = _recipient(makerspace)
    archive = _archive(makerspace)
    calls = _successful_build_stubs(monkeypatch)
    paths = _track_tempdirs(monkeypatch, tmp_path)
    original_write_json = archive_builder._write_json

    def revoke_after_manifest(path, value):
        original_write_json(path, value)
        if path.name == "manifest.json":
            MakerspaceArchiveRecipient.objects.filter(pk=recipient.pk).update(
                revoked_at=timezone.now()
            )

    monkeypatch.setattr(archive_builder, "_write_json", revoke_after_manifest)

    with pytest.raises(archive_builder.BackupBuildError):
        archive_builder.build_archive(archive)

    assert calls == []
    assert paths and all(not path.exists() for path in paths)


def test_age_argv_projects_recorded_duplicates_literally(monkeypatch, settings):
    settings.BACKUP_AGE_RECIPIENT = VALID_RECIPIENT
    makerspace = Makerspace.objects.create(
        name="Duplicate argv", slug="archive-duplicate-argv",
        superadmin_access_enabled=True,
    )
    _recipient(makerspace)
    archive = _archive(makerspace)
    calls = _successful_build_stubs(monkeypatch)

    encrypted, _manifest, tempdir, _digest = archive_builder.build_archive(archive)
    try:
        plain = Path(tempdir.name, f"{archive.id}.tar")
        assert calls[0] == [
            "age", "-r", VALID_RECIPIENT, "-r", VALID_RECIPIENT,
            "-o", str(encrypted), str(plain),
        ]
    finally:
        tempdir.cleanup()
