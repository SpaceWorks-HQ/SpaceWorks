from copy import deepcopy
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.tenant_migration.tenant_dump_errors import TenantDumpTargetError
from apps.tenant_migration.tenant_dump_target import (
    install_and_verify_target_encryption,
    preflight_target_identity_input,
)
from apps.tenant_migration.tenant_dump_target_deks import TargetInstallSafety
from apps.tenant_migration.tenant_dump_target_identities import (
    preflight_target_identities,
)
from tests.tenant_migration.tenant_dump_d5_helpers import (
    age_recipient,
    frozen_recipient,
    target_manifest,
    write_read_only_mountinfo,
)


pytestmark = pytest.mark.django_db
IDENTITY_BYTES = b"AGE-SECRET-KEY-1TENANT-OPERATOR-OWNED\n"


def _mounted_identity(tmp_path, monkeypatch, *, seed=11, mode=0o600, read_only=True):
    path = tmp_path / f"identity-{seed}.txt"
    path.write_bytes(IDENTITY_BYTES)
    path.chmod(mode)
    mountinfo = write_read_only_mountinfo(
        tmp_path, path, read_only=read_only
    )
    recipient = age_recipient(seed)
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_identities.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=(recipient + "\n").encode("ascii")
        ),
    )
    return path, mountinfo


def _assert_no_database_write(queries):
    mutating = ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP ")
    assert not [
        query["sql"]
        for query in queries
        if query["sql"].lstrip().upper().startswith(mutating)
    ]


def test_only_read_only_mode_0600_mount_is_accepted_without_retention(
    tmp_path, monkeypatch
):
    operations = tmp_path / "operations"
    operations.mkdir()
    path, mountinfo = _mounted_identity(tmp_path, monkeypatch)

    with CaptureQueriesContext(connection) as queries:
        result = preflight_target_identities(
            (path,),
            (frozen_recipient(11),),
            environ={},
            command_argv=(),
            mountinfo_path=mountinfo,
        )

    assert result[0].path == path.resolve()
    assert result[0].public_recipient == age_recipient(11)
    assert path.read_bytes() == IDENTITY_BYTES
    assert not tuple(operations.iterdir())
    _assert_no_database_write(queries)


@pytest.mark.parametrize(
    ("mode", "read_only", "expected_code"),
    (
        (0o640, True, "identity_path_mode"),
        (0o600, False, "identity_mount_writable"),
    ),
)
def test_identity_mount_permissions_fail_closed(
    mode, read_only, expected_code, tmp_path, monkeypatch
):
    path, mountinfo = _mounted_identity(
        tmp_path, monkeypatch, mode=mode, read_only=read_only
    )

    with pytest.raises(TenantDumpTargetError) as caught:
        preflight_target_identities(
            (path,),
            (frozen_recipient(11),),
            environ={},
            mountinfo_path=mountinfo,
        )

    assert caught.value.code == expected_code


def test_identity_mount_cannot_be_a_symlink(tmp_path, monkeypatch):
    path, mountinfo = _mounted_identity(tmp_path, monkeypatch)
    link = tmp_path / "identity-link"
    link.symlink_to(path)
    link.chmod(0o600)

    with pytest.raises(TenantDumpTargetError) as caught:
        preflight_target_identities(
            (link,),
            (frozen_recipient(11),),
            environ={},
            mountinfo_path=mountinfo,
        )

    assert caught.value.code == "identity_path_type"


@pytest.mark.parametrize(
    "channel",
    ("argv_path", "argv_inline", "environment_path", "environment_inline"),
)
def test_identity_supplied_through_argv_or_environment_is_refused(
    channel, tmp_path, monkeypatch
):
    path, mountinfo = _mounted_identity(tmp_path, monkeypatch)
    argv = ()
    environ = {}
    if channel == "argv_path":
        argv = ("tenant-dump-target", "--identity", str(path))
    elif channel == "argv_inline":
        argv = ("tenant-dump-target", IDENTITY_BYTES.decode())
    elif channel == "environment_path":
        environ = {"AGE_IDENTITY": str(path)}
    else:
        environ = {"UNRELATED_NAME": IDENTITY_BYTES.decode()}

    with pytest.raises(TenantDumpTargetError) as caught:
        preflight_target_identities(
            (path,),
            (frozen_recipient(11),),
            environ=environ,
            command_argv=argv,
            mountinfo_path=mountinfo,
        )

    assert caught.value.code in {"inline_identity", "identity_environment"}


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("no_match", "outer_platform_only_or_no_match"),
        ("outer_platform_only", "outer_platform_only_or_no_match"),
        ("recipient_set_mismatch", "recipient_set_mismatch"),
        ("no_verified_tenant_recipient", "no_verified_tenant_recipient"),
    ),
)
def test_recipient_preflight_refusals_make_no_destructive_database_write(
    case, expected_code, tmp_path, monkeypatch
):
    path, mountinfo = _mounted_identity(tmp_path, monkeypatch, seed=11)
    frozen = (frozen_recipient(12),)
    if case == "recipient_set_mismatch":
        frozen = (frozen_recipient(11), frozen_recipient(12))
    elif case == "no_verified_tenant_recipient":
        frozen = ()

    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(TenantDumpTargetError) as caught:
            preflight_target_identities(
                (path,),
                frozen,
                environ={},
                command_argv=(),
                mountinfo_path=mountinfo,
            )

    assert caught.value.code == expected_code
    _assert_no_database_write(queries)


@pytest.mark.parametrize("makerspace_id", (0, -1, False, True))
def test_manifest_makerspace_identity_must_be_a_positive_non_boolean_integer(
    makerspace_id, monkeypatch
):
    manifest = target_manifest(9)
    manifest["source"]["makerspace_id"] = makerspace_id
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target.preflight_target_identities",
        unexpected,
    )
    with pytest.raises(TenantDumpTargetError) as caught:
        preflight_target_identity_input(manifest, ())

    assert caught.value.code == "manifest_invalid"
    assert called is False


def test_preflight_is_digest_bound_to_the_exact_manifest(tmp_path, monkeypatch):
    path, mountinfo = _mounted_identity(tmp_path, monkeypatch)
    manifest = target_manifest(9)
    preflight = preflight_target_identity_input(
        manifest,
        (path,),
        environ={},
        command_argv=(),
        mountinfo_path=mountinfo,
    )

    changed = deepcopy(manifest)
    changed["source"]["makerspace_id"] = 10
    helper_called = False

    def unexpected(*_args, **_kwargs):
        nonlocal helper_called
        helper_called = True

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target.install_target_deks",
        unexpected,
    )
    with pytest.raises(TenantDumpTargetError) as caught:
        install_and_verify_target_encryption(
            changed,
            tmp_path / "tenant-deks.age",
            preflight,
            safety=TargetInstallSafety(
                non_routable=True,
                recovery_mode="target_import",
            ),
        )

    assert caught.value.code == "identity_preflight_mismatch"
    assert helper_called is False
