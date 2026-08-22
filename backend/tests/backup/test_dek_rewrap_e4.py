import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from apps.backup.dek_rewrap import (
    StagedDekRow,
    enumerate_staged_deks,
    seal_staged_deks,
    verify_sealed_dek_inventory,
)
from apps.backup.main_projection_registry import RowDisposition, table_rules
from apps.backup.recipient_selection import BackupBuildError
from apps.encryption.models import MakerspaceEncryptionKey
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)


DEK = b"D" * 32
WRAPPED_ONE = b"immutable-wrapped-one"
WRAPPED_TWO = b"immutable-wrapped-two"
RECIPIENTS = ("age1tenant-e4-one", "age1tenant-e4-two")


def _row(row_id=1, version=1, wrapped=WRAPPED_ONE, **changes):
    value = StagedDekRow(
        row_identity=row_id,
        makerspace_id=41,
        version=version,
        status=MakerspaceEncryptionKey.Status.ACTIVE,
        broker_backend=MakerspaceEncryptionKey.BrokerBackend.LOCAL,
        broker_key_id="local:test",
        wrapped_dek=wrapped,
        wrapped_dek_sha256=hashlib.sha256(wrapped).hexdigest(),
    )
    return replace(value, **changes)


def _fake_age(commands):
    def run(command, *, input, **_kwargs):
        commands.append(tuple(command))
        output = Path(command[command.index("-o") + 1])
        # Model an opaque envelope so plaintext-leak assertions are meaningful.
        output.write_bytes(b"sealed:" + hashlib.sha256(input).digest())
    return run


def _record(row, root):
    path = root / f"{row.row_identity}.json.age"
    return {
        "row_identity": row.row_identity,
        "makerspace_id": row.makerspace_id,
        "version": row.version,
        "status": row.status,
        "source_broker_backend": row.broker_backend,
        "source_broker_key_id": row.broker_key_id,
        "source_wrapped_dek_sha256": row.wrapped_dek_sha256,
        "path": f"keys/deks/{row.row_identity}.json.age",
        "size_bytes": path.stat().st_size,
        "ciphertext_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "extra", "substituted"))
def test_sealed_inventory_must_equal_immutable_staging(tmp_path, mutation):
    first = _row()
    second = _row(2, 2, WRAPPED_TWO, status=MakerspaceEncryptionKey.Status.ROTATED)
    for row in (first, second):
        (tmp_path / f"{row.row_identity}.json.age").write_bytes(
            f"sealed-{row.row_identity}".encode()
        )
    records = [_record(first, tmp_path), _record(second, tmp_path)]
    if mutation == "missing":
        records.pop()
    elif mutation == "duplicate":
        records.append(dict(records[0]))
    elif mutation == "extra":
        records.append({**records[0], "row_identity": 999})
    else:
        records[0]["source_wrapped_dek_sha256"] = "0" * 64

    with pytest.raises(BackupBuildError):
        verify_sealed_dek_inventory((first, second), records, tmp_path)


@pytest.mark.parametrize(
    "row",
    (
        _row(status="future_status"),
        _row(broker_backend="future_broker"),
        _row(wrapped_dek_sha256="0" * 64),
        _row(row_identity=0),
    ),
)
def test_unsupported_or_substituted_staging_refuses_before_broker(
    monkeypatch, tmp_path, row
):
    calls = []
    monkeypatch.setattr(
        "apps.backup.dek_rewrap.services.broker_for_backend",
        lambda backend: calls.append(backend),
    )
    with pytest.raises(BackupBuildError, match="unsupported or substituted"):
        seal_staged_deks((row,), RECIPIENTS, tmp_path)
    assert calls == []


def test_duplicate_staged_row_refuses_before_broker(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "apps.backup.dek_rewrap.services.broker_for_backend",
        lambda backend: calls.append(backend),
    )
    row = _row()
    with pytest.raises(BackupBuildError, match="duplicate key row"):
        seal_staged_deks((row, row), RECIPIENTS, tmp_path)
    assert calls == []


def test_adapter_refuses_mutable_or_queryset_shaped_input(tmp_path):
    with pytest.raises(BackupBuildError, match="immutable staged enumeration"):
        seal_staged_deks([_row()], RECIPIENTS, tmp_path)


def test_adapter_calls_broker_only_for_exact_enumerated_wrapped_bytes(
    monkeypatch, tmp_path
):
    rows = (
        _row(),
        _row(2, 2, WRAPPED_TWO, status=MakerspaceEncryptionKey.Status.ROTATED),
    )
    calls = []
    commands = []

    class Broker:
        def unwrap_dek(self, wrapped, makerspace_id, version):
            calls.append((wrapped, makerspace_id, version))
            return bytes([version]) * 32

    monkeypatch.setattr(
        "apps.backup.dek_rewrap.services.broker_for_backend", lambda _value: Broker()
    )
    monkeypatch.setattr(
        "apps.backup.dek_rewrap.subprocess.run", _fake_age(commands)
    )

    sealed = seal_staged_deks(rows, RECIPIENTS, tmp_path)

    assert calls == [(WRAPPED_ONE, 41, 1), (WRAPPED_TWO, 41, 2)]
    assert len(sealed) == 2
    assert all(command.count("-r") == len(RECIPIENTS) for command in commands)
    assert all(value in command for command in commands for value in RECIPIENTS)
    assert all(WRAPPED_ONE.decode() not in " ".join(command) for command in commands)


def test_encryption_key_rows_are_slice_owned_in_projection_registry():
    rule = next(
        item for item in table_rules()
        if item.model._meta.label == "encryption.MakerspaceEncryptionKey"
    )
    assert rule.disposition == RowDisposition.COPY_TO_SLICE
    assert rule.predicate.any_paths == ("makerspace",)


def test_failure_exception_retains_no_plaintext_context(monkeypatch, tmp_path):
    class Broker:
        def unwrap_dek(self, *_args):
            raise RuntimeError(base64.b64encode(DEK).decode())

    monkeypatch.setattr(
        "apps.backup.dek_rewrap.services.broker_for_backend", lambda _value: Broker()
    )
    with pytest.raises(BackupBuildError) as caught:
        seal_staged_deks((_row(),), RECIPIENTS, tmp_path)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert base64.b64encode(DEK).decode() not in repr(caught.value)


def test_enumeration_is_immutable_and_plaintext_reaches_no_retained_surface(
    monkeypatch, caplog, tmp_path
):
    space = Makerspace.objects.create(name="E4 W8", slug="e4-w8")
    key = MakerspaceEncryptionKey.objects.create(
        makerspace=space,
        version=1,
        status=MakerspaceEncryptionKey.Status.ACTIVE,
        broker_backend=MakerspaceEncryptionKey.BrokerBackend.LOCAL,
        broker_key_id="local:test",
        wrapped_dek=WRAPPED_ONE,
    )
    staged = enumerate_staged_deks(space.pk)
    MakerspaceEncryptionKey.objects.filter(pk=key.pk).update(wrapped_dek=b"substitute")
    calls = []

    class Broker:
        def unwrap_dek(self, wrapped, makerspace_id, version):
            calls.append((wrapped, makerspace_id, version))
            return DEK

    monkeypatch.setattr(
        "apps.backup.dek_rewrap.services.broker_for_backend", lambda _value: Broker()
    )
    monkeypatch.setattr(
        "apps.backup.dek_rewrap.subprocess.run", _fake_age([])
    )

    sealed = seal_staged_deks(staged, RECIPIENTS, tmp_path)

    assert calls == [(WRAPPED_ONE, space.pk, 1)]
    plaintext_markers = (
        DEK,
        base64.b64encode(DEK),
        DEK.hex().encode(),
    )
    retained = json.dumps(sealed, sort_keys=True).encode()
    retained += "\n".join(record.getMessage() for record in caplog.records).encode()
    retained += bytes(MakerspaceEncryptionKey.objects.get(pk=key.pk).wrapped_dek)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            retained += path.read_bytes()
    assert all(marker not in retained for marker in plaintext_markers)
