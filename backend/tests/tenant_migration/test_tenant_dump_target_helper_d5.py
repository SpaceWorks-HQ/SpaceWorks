from io import BytesIO
import struct
from types import SimpleNamespace

import pytest

from apps.audit.models import AuditLog
from apps.encryption.brokers.base import WrappedDek
from apps.encryption.models import MakerspaceEncryptionKey
from apps.tenant_migration import tenant_dump_target_helper
from apps.tenant_migration.tenant_dump_dek_helper import PAYLOAD_MAGIC
from apps.tenant_migration.tenant_dump_target_protocol import INSTALL_PROTOCOL
from apps.tenant_migration.tenant_dump_target_helper import install_deks
from tests.tenant_migration.tenant_dump_d5_helpers import (
    importing_space,
    key_inventory,
)


pytestmark = pytest.mark.django_db
PLAINTEXT_DEK = b"target-helper-transient-dek-value"[:32].ljust(32, b"!")


def _record(owner, version, status, dek):
    encoded_status = status.encode("ascii")
    return b"".join(
        (
            struct.pack(">QI", owner, version),
            struct.pack(">H", len(encoded_status)),
            encoded_status,
            struct.pack(">H", len(dek)),
            dek,
        )
    )


def _payload(space_id, *, fault):
    rows = [
        _record(space_id, 3, "rotated", PLAINTEXT_DEK),
        _record(space_id, 7, "active", b"a" * 32),
    ]
    count = 2
    if fault == "count":
        count = 3
    elif fault == "owner":
        rows[0] = _record(space_id + 1, 3, "rotated", PLAINTEXT_DEK)
    elif fault == "status":
        rows[0] = _record(space_id, 3, "active", PLAINTEXT_DEK)
    elif fault == "order":
        rows.reverse()
    elif fault == "truncated":
        rows[1] = rows[1][:-1]
    payload = PAYLOAD_MAGIC + struct.pack(">I", count) + b"".join(rows)
    return payload + (b"unexpected" if fault == "trailing" else b"")


class _AgeProcess:
    def __init__(self, payload, *, returncode=0):
        self.stdin = None
        self.stdout = BytesIO(payload)
        self.returncode = returncode
        self.killed = False
        self.waited = 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self):
        self.waited += 1
        return self.returncode


class _Broker:
    backend = "local"

    def __init__(self, *, fail=False):
        self.fail = fail

    def wrap_dek(self, dek, makerspace_id, version):
        if self.fail and version == 7:
            raise RuntimeError(PLAINTEXT_DEK.decode("ascii"))
        return WrappedDek(
            dek=dek,
            wrapped_dek=f"wrapped-by-target-{makerspace_id}-{version}".encode(),
            broker_key_id="target-broker",
        )


@pytest.mark.parametrize(
    "fault",
    (
        "count",
        "owner",
        "status",
        "order",
        "truncated",
        "trailing",
        "broker",
        "audit",
        "age_exit",
    ),
)
def test_every_helper_fault_reaps_age_and_rolls_back_without_dek_residue(
    fault, tmp_path, monkeypatch, caplog
):
    space = importing_space(f"d5-helper-{fault}")
    identity = tmp_path / "tenant-identity.agekey"
    identity.write_bytes(b"operator-owned identity")
    envelope = tmp_path / "tenant-deks.age"
    envelope.write_bytes(b"opaque ciphertext")
    process = _AgeProcess(
        _payload(space.pk, fault=fault),
        returncode=9 if fault == "age_exit" else 0,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_identities._validated_identity_mount",
        lambda path, **_kwargs: identity,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_helper.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        "apps.encryption.services.configured_broker",
        lambda: _Broker(fail=fault == "broker"),
    )
    if fault == "audit":
        monkeypatch.setattr(
            "apps.audit.services.record",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError(PLAINTEXT_DEK.decode("ascii"))
            ),
        )
    request = {
        "identity_paths": (str(identity),),
        "envelope_path": str(envelope),
        "makerspace_id": space.pk,
        "inventory": key_inventory(space.pk),
    }

    with pytest.raises(Exception):
        install_deks(request)

    assert process.waited >= 1
    assert process.poll() is not None
    assert process.stdout.closed
    assert not MakerspaceEncryptionKey.objects.filter(makerspace=space).exists()
    assert not AuditLog.objects.filter(
        makerspace=space,
        action="tenant_migration.target_deks_installed",
    ).exists()
    residue = caplog.text
    residue += "".join(
        path.read_text(errors="ignore")
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert PLAINTEXT_DEK.decode("ascii") not in residue


def test_helper_process_boundary_suppresses_secret_bearing_exception(
    monkeypatch, caplog
):
    stdout = BytesIO()
    monkeypatch.setattr(tenant_dump_target_helper.django, "setup", lambda: None)
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_protocol.decode_request",
        lambda _payload: (INSTALL_PROTOCOL, {}),
    )
    monkeypatch.setattr(
        tenant_dump_target_helper,
        "install_deks",
        lambda _request: (_ for _ in ()).throw(
            RuntimeError(PLAINTEXT_DEK.decode("ascii"))
        ),
    )
    monkeypatch.setattr(
        tenant_dump_target_helper.sys,
        "stdin",
        SimpleNamespace(buffer=BytesIO(b"bounded request")),
    )
    monkeypatch.setattr(
        tenant_dump_target_helper.sys,
        "stdout",
        SimpleNamespace(buffer=stdout),
    )

    result = tenant_dump_target_helper.main()

    assert result == 1
    assert stdout.getvalue() == b""
    assert PLAINTEXT_DEK.decode("ascii") not in caplog.text


def test_helper_success_installs_exact_inventory_and_returns_only_versions(
    tmp_path, monkeypatch
):
    space = importing_space("d5-helper-success")
    identity = tmp_path / "tenant-identity.agekey"
    identity.write_bytes(b"operator-owned identity")
    envelope = tmp_path / "tenant-deks.age"
    envelope.write_bytes(b"opaque ciphertext")
    process = _AgeProcess(_payload(space.pk, fault="none"))
    launched = {}
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_identities._validated_identity_mount",
        lambda path, **_kwargs: identity,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_helper.subprocess.Popen",
        lambda command, **kwargs: launched.update(command=command, kwargs=kwargs)
        or process,
    )
    monkeypatch.setattr(
        "apps.encryption.services.configured_broker", lambda: _Broker()
    )

    result = install_deks(
        {
            "identity_paths": (str(identity),),
            "envelope_path": str(envelope),
            "makerspace_id": space.pk,
            "inventory": key_inventory(space.pk),
        }
    )

    assert result == {"installed_versions": [3, 7]}
    assert MakerspaceEncryptionKey.objects.filter(
        makerspace=space, status="active"
    ).count() == 1
    assert set(
        MakerspaceEncryptionKey.objects.filter(makerspace=space).values_list(
            "version", "status"
        )
    ) == {(3, "rotated"), (7, "active")}
    assert all(
        PLAINTEXT_DEK not in bytes(value)
        for value in MakerspaceEncryptionKey.objects.filter(
            makerspace=space
        ).values_list("wrapped_dek", flat=True)
    )
    audit = AuditLog.objects.get(
        makerspace=space,
        action="tenant_migration.target_deks_installed",
    )
    assert str(identity) not in repr(audit.meta)
    assert b"operator-owned identity" not in repr(audit.meta).encode()
    assert set(tmp_path.iterdir()) == {identity, envelope}
    assert process.waited >= 1 and process.stdout.closed
    assert PLAINTEXT_DEK.decode("ascii") not in repr(launched)
    assert str(identity) not in launched["command"]
    assert any(value.startswith("/proc/self/fd/") for value in launched["command"])
