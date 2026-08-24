import base64

from apps.ed25519 import encode_key, generate_keypair
import pytest

from apps.backup import import_preflight
from apps.backup.import_preflight import ImportPreflightError
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


def _apply_refusal(case, fixture, settings):
    expected = fixture.expected_sha256
    if case == "outer_digest_mismatch":
        return "0" * 64
    if case == "manifest_signature":
        fixture.manifest["archive_signature"]["value"] = base64.b64encode(
            b"invalid" * 9 + b"x"
        ).decode()
        fixture.write(sign=False)
    elif case == "signer_identity":
        _private, public = generate_keypair()
        settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY = encode_key(public)
    elif case == "format_lane_d":
        fixture.manifest["format"] = "spaceworks-tenant-dump-v1"
        fixture.write()
    elif case == "format_obsolete":
        fixture.manifest["format"] = "spaceworks-tenant-migration-v1"
        fixture.write()
    elif case == "format_version":
        fixture.manifest["protocol_version"] = "spaceworks-lane-e-b1-v0"
        fixture.write()
    elif case == "missing_component":
        fixture.members.pop(fixture.manifest["slice_components"][0]["ciphertext_path"])
        fixture.write()
    elif case == "component_digest":
        path = fixture.manifest["slice_components"][0]["ciphertext_path"]
        fixture.members[path] = b"altered tenant slice"
        fixture.write()
    elif case == "undeclared_member":
        fixture.members["unexpected.txt"] = b"not declared"
        fixture.write()
    elif case == "continuity_secret_names":
        fixture.secrets.pop("CRON_SECRET")
        fixture.write()
    elif case == "continuity_secret_value":
        fixture.secrets["CRON_SECRET"] = "secret-sentinel\nsecond-line"
        fixture.write()
    elif case == "postgres_major":
        fixture.manifest["postgres"] = {
            "source_server_major": 15,
            "client": "pg_dump (PostgreSQL) 15.8",
        }
        fixture.write()
    elif case == "source_build":
        changed_build = {"source_hash": "9" * 64}
        fixture.manifest["build_identity"]["build"] = changed_build
        fixture.manifest["build"] = changed_build.copy()
        fixture.write()
    elif case == "component_policy":
        fixture.manifest["main_component"]["size_bytes"] = 0
        fixture.manifest["contents"][0]["size"] = 0
        fixture.write()
    return expected


@pytest.mark.parametrize(
    "reason",
    (
        "outer_digest_mismatch",
        "manifest_signature",
        "signer_identity",
        "format_lane_d",
        "format_obsolete",
        "format_version",
        "missing_component",
        "component_digest",
        "undeclared_member",
        "continuity_secret_names",
        "continuity_secret_value",
        "postgres_major",
        "source_build",
        "component_policy",
    ),
)
def test_each_refusal_is_specific_and_side_effect_free(
    reason, monkeypatch, settings, tmp_path
):
    fixture = make_import_fixture(tmp_path)
    _configure_target(monkeypatch)
    expected = _apply_refusal(reason, fixture, settings)
    original_env = b"SECRET_KEY='target-value'\n"
    env_path = tmp_path / ".env"
    env_path.write_bytes(original_env)
    object_calls = []
    audit_calls = []
    process_calls = []
    monkeypatch.setattr(
        "apps.backup.storage.upload_archive",
        lambda *args, **kwargs: object_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "apps.backup.storage.client",
        lambda *args, **kwargs: object_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "apps.audit.services.record",
        lambda *args, **kwargs: audit_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )

    kwargs = preflight_kwargs(fixture)
    kwargs["expected_sha256"] = expected
    with pytest.raises(ImportPreflightError) as caught:
        import_preflight.validate_import_preflight(**kwargs)

    message = str(caught.value)
    assert f"[{reason}]" in message
    assert "secret-sentinel" not in message
    assert env_path.read_bytes() == original_env
    assert not list(tmp_path.glob(".env.pre-restore-*"))
    assert BackupArchive.objects.count() == 0
    assert RestoreOperation.objects.count() == 0
    assert object_calls == []
    assert audit_calls == []
    assert process_calls == []
