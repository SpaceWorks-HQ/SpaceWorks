from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from apps.accounts.models import User
from apps.backup import import_preflight
from apps.backup.models import BackupArchive, RestoreOperation
from tests.backup.import_preflight_test_support import (
    POSTGRES_MAJOR,
    SOURCE_HASH,
    make_import_fixture,
    preflight_kwargs,
)


pytestmark = pytest.mark.django_db


def _configure_target(monkeypatch):
    monkeypatch.setattr(import_preflight, "build_info", lambda: {
        "source_hash": SOURCE_HASH
    })
    monkeypatch.setattr(import_preflight, "server_major", lambda: POSTGRES_MAJOR)


def _command_options(fixture):
    return {
        "encrypted_file": str(fixture.encrypted),
        "bundle": str(fixture.bundle),
        "manifest": str(fixture.manifest_file),
        "continuity_secrets": str(fixture.secrets_file),
        "expected_sha256": fixture.expected_sha256,
    }


def test_successful_preflight_has_no_deployment_side_effects(monkeypatch, tmp_path):
    fixture = make_import_fixture(tmp_path)
    _configure_target(monkeypatch)
    original_env = b"SECRET_KEY='still-target'\n"
    env_path = tmp_path / ".env"
    env_path.write_bytes(original_env)
    calls = {"object": [], "audit": [], "process": []}
    monkeypatch.setattr(
        "apps.backup.storage.upload_archive",
        lambda *args, **kwargs: calls["object"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        "apps.backup.storage.client",
        lambda *args, **kwargs: calls["object"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        "apps.audit.services.record",
        lambda *args, **kwargs: calls["audit"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: calls["process"].append((args, kwargs)),
    )

    result = import_preflight.validate_import_preflight(
        **preflight_kwargs(fixture)
    )

    assert result.archive_sha256 == fixture.expected_sha256
    assert result.host_restore_gate == "not configured"
    assert env_path.read_bytes() == original_env
    assert not list(tmp_path.glob(".env.pre-restore-*"))
    assert BackupArchive.objects.count() == 0
    assert RestoreOperation.objects.count() == 0
    assert calls == {"object": [], "audit": [], "process": []}


def test_expected_digest_is_optional_but_still_computed(monkeypatch, tmp_path):
    fixture = make_import_fixture(tmp_path)
    _configure_target(monkeypatch)
    options = preflight_kwargs(fixture)
    options["expected_sha256"] = None

    result = import_preflight.validate_import_preflight(**options)

    assert result.archive_sha256 == fixture.expected_sha256


def test_preflight_and_import_commands_share_the_same_refusal(
    monkeypatch, tmp_path
):
    fixture = make_import_fixture(tmp_path)
    _configure_target(monkeypatch)
    missing = fixture.manifest["slice_components"][0]["ciphertext_path"]
    fixture.members.pop(missing)
    fixture.write()
    actor = User.objects.create_superuser(
        username="preflight-parity", password="not-used"
    )
    options = _command_options(fixture)

    with pytest.raises(CommandError) as preflight_error:
        call_command("preflight_backup_import", stdout=StringIO(), **options)
    with pytest.raises(CommandError) as import_error:
        call_command(
            "import_backup_archive",
            username=actor.username,
            stdout=StringIO(),
            **options,
        )

    assert str(preflight_error.value) == str(import_error.value)
    assert "[missing_component]" in str(preflight_error.value)
    assert BackupArchive.objects.count() == 0
    assert RestoreOperation.objects.count() == 0
