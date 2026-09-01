from io import BytesIO
from pathlib import Path

import pytest
from django.test import override_settings

from apps.backup.dek_rewrap import StagedDekRow
from apps.backup.digests import sha256_bytes
from apps.encryption.cache import CacheKey, dek_cache
from apps.tenant_migration.tenant_dump_dek_helper import stream_envelope
from apps.tenant_migration.tenant_dump_deks import seal_tenant_deks
from apps.tenant_migration.tenant_dump_errors import TenantDumpBuildError


PLAINTEXT_DEK = b"p" * 32


def _row():
    wrapped = b"source-broker-wrapped-key"
    return StagedDekRow(
        row_identity=17,
        makerspace_id=23,
        version=5,
        status="active",
        broker_backend="local",
        broker_key_id="source-master",
        wrapped_dek=wrapped,
        wrapped_dek_sha256=sha256_bytes(wrapped),
    )


class _AgeProcess:
    def __init__(self, *, returncode=0, write_failure=False):
        self.stdin = _FailingPipe() if write_failure else BytesIO()
        self.returncode = None
        self.exit_code = returncode
        self.killed = False
        self.waited = 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self):
        self.waited += 1
        if self.returncode is None:
            self.returncode = self.exit_code
        return self.returncode


class _FailingPipe(BytesIO):
    def write(self, _payload):
        raise RuntimeError(PLAINTEXT_DEK.decode())


class _Broker:
    def __init__(self, *, fail=False):
        self.fail = fail

    def unwrap_dek(self, _wrapped, _makerspace_id, _version):
        if self.fail:
            raise RuntimeError(PLAINTEXT_DEK.decode())
        return PLAINTEXT_DEK


@pytest.mark.parametrize("fault", ("unwrap", "write", "age_exit"))
def test_helper_faults_terminate_reap_and_do_not_expose_dek(
    fault, monkeypatch, tmp_path, caplog
):
    process = _AgeProcess(
        returncode=7 if fault == "age_exit" else 0,
        write_failure=fault == "write",
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_dek_helper.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        "apps.encryption.services.broker_for_backend",
        lambda _backend: _Broker(fail=fault == "unwrap"),
    )
    cache_key = CacheKey(23, 5, "local", "source-master")
    output = tmp_path / "anonymous-pipe-surrogate"
    with override_settings(PII_DEK_CACHE_TTL_SECONDS=60):
        dek_cache.set(cache_key, PLAINTEXT_DEK)
        with output.open("wb") as handle:
            result = stream_envelope((_row(),), ("age1tenant",), handle)

    assert result == 1
    assert process.waited >= 1
    assert process.poll() is not None
    assert process.stdin.closed
    assert dek_cache.get(cache_key) is None
    assert PLAINTEXT_DEK.decode() not in caplog.text
    assert PLAINTEXT_DEK not in output.read_bytes()


class _ParentProcess:
    def __init__(self, *, returncode=0, fail_communicate=False):
        self.stdin = BytesIO()
        self.stdout = BytesIO()
        self.returncode = returncode
        self.fail_communicate = fail_communicate
        self.killed = False
        self.waited = 0
        self.request = b""

    def communicate(self, request):
        self.request = request
        if self.fail_communicate:
            self.returncode = None
            raise RuntimeError(PLAINTEXT_DEK.decode())
        return b"age ciphertext", None

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self):
        self.waited += 1
        return self.returncode


@pytest.mark.parametrize("fault", ("helper_exit", "pipe", "filesystem_write"))
def test_key_free_parent_removes_unpublished_output_for_every_fault(
    fault, monkeypatch, tmp_path, caplog
):
    process = _ParentProcess(
        returncode=9 if fault == "helper_exit" else 0,
        fail_communicate=fault == "pipe",
    )
    popen_call = {}
    parent_unwrap_calls = 0

    def refuse_parent_unwrap(_backend):
        nonlocal parent_unwrap_calls
        parent_unwrap_calls += 1
        raise AssertionError("the parent reached the source broker")

    def fake_popen(command, **kwargs):
        popen_call.update(command=command, kwargs=kwargs)
        return process

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_deks.subprocess.Popen", fake_popen
    )
    monkeypatch.setattr(
        "apps.encryption.services.broker_for_backend", refuse_parent_unwrap
    )
    if fault == "filesystem_write":
        monkeypatch.setattr(
            Path,
            "open",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
        )
    destination = tmp_path / "keys" / "tenant-deks.age"

    with pytest.raises(TenantDumpBuildError) as caught:
        seal_tenant_deks((_row(),), (_row(),), ("age1tenant",), destination)

    assert process.waited >= 1
    assert process.poll() is not None
    assert process.stdin.closed and process.stdout.closed
    assert not destination.exists()
    assert not list(destination.parent.glob("*.tmp"))
    assert parent_unwrap_calls == 0
    captured = repr(popen_call) + repr(process.request) + caplog.text + str(caught.value)
    assert PLAINTEXT_DEK.decode() not in captured
    assert "env" not in popen_call["kwargs"]
