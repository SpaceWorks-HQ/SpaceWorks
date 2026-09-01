from io import BytesIO

import pytest

from apps.encryption.models import MakerspaceEncryptionKey
from apps.tenant_migration.tenant_dump_errors import TenantDumpTargetError
from apps.tenant_migration.tenant_dump_target_deks import (
    _run_helper,
    install_target_deks,
)
from tests.tenant_migration.tenant_dump_d5_helpers import (
    envelope_manifest,
    importing_space,
    safe_target,
    target_identity,
)


pytestmark = pytest.mark.django_db
PLAINTEXT_DEK = b"d5-parent-must-never-see-this!!"[:32].ljust(32, b"!")
IDENTITY_SECRET = "AGE-SECRET-KEY-1D5-ENVIRONMENT-LEAK"


def test_parent_sends_only_key_free_inventory_to_bounded_helper(
    tmp_path, monkeypatch
):
    space = importing_space("d5-key-free-parent")
    manifest, envelope = envelope_manifest(tmp_path, space.pk)
    captured = {}

    def helper(request):
        captured["request"] = request
        return {"installed_versions": [3, 7]}

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_deks._run_helper", helper
    )
    monkeypatch.setattr(
        "apps.encryption.services.configured_broker",
        lambda: (_ for _ in ()).throw(AssertionError("parent reached target broker")),
    )

    versions = install_target_deks(
        manifest,
        envelope,
        (target_identity(tmp_path / "identity", 11),),
        safety=safe_target(),
    )

    request = captured["request"]
    assert versions == (3, 7)
    assert PLAINTEXT_DEK not in request
    assert b'"dek"' not in request and b'"dek_base64"' not in request


class _ParentProcess:
    def __init__(self, fault):
        self.fault = fault
        self.stdin = BytesIO()
        self.stdout = BytesIO()
        self.returncode = 7 if fault == "nonzero" else 0
        self.pid = 90210
        self.waited = 0

    def communicate(self, _request, timeout):
        assert timeout > 0
        if self.fault == "communicate":
            self.returncode = None
            raise RuntimeError(PLAINTEXT_DEK.decode("ascii"))
        outputs = {
            "nonzero": b"{}",
            "empty": b"",
            "invalid_json": b"not-json",
            "invalid_shape": b"[]",
        }
        return outputs[self.fault], None

    def poll(self):
        return self.returncode

    def wait(self):
        self.waited += 1
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


def _exception_text(error):
    values = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        values.append(str(current))
        current = current.__cause__ or current.__context__
    return " ".join(values)


@pytest.mark.parametrize(
    "fault", ("communicate", "nonzero", "empty", "invalid_json", "invalid_shape")
)
def test_parent_faults_reap_helper_and_leave_no_secret_residue(
    fault, tmp_path, monkeypatch, caplog
):
    process = _ParentProcess(fault)
    popen = {}
    killed = []
    monkeypatch.setenv("LEAKY_IDENTITY", IDENTITY_SECRET)
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_deks.subprocess.Popen",
        lambda command, **kwargs: popen.update(command=command, kwargs=kwargs)
        or process,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target_deks.os.killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    with pytest.raises(TenantDumpTargetError) as caught:
        _run_helper(b'{"protocol":"key-free"}\n')

    assert caught.value.code == "target_helper_failed"
    assert popen["kwargs"]["start_new_session"] is True
    assert popen["kwargs"]["close_fds"] is True
    assert PLAINTEXT_DEK.decode("ascii") not in repr(popen["command"])
    assert process.waited >= 1
    assert process.poll() is not None
    assert process.stdin.closed and process.stdout.closed
    if fault == "communicate":
        assert killed
    residue = (
        repr(popen)
        + caplog.text
        + _exception_text(caught.value)
        + "".join(
            path.read_text(errors="ignore")
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    assert PLAINTEXT_DEK.decode("ascii") not in residue
    assert IDENTITY_SECRET not in repr(popen["kwargs"]["env"])
    stored = MakerspaceEncryptionKey.objects.values_list("wrapped_dek", flat=True)
    assert all(PLAINTEXT_DEK not in bytes(value) for value in stored)
