import hashlib
import uuid

import pytest

from apps.backup.host_run_ledger import RunLedger
from apps.tenant_migration.tenant_restore_objects import (
    load_object,
    rollback_created_objects,
)
from apps.tenant_migration.tenant_restore_types import ObjectEntry, TenantRestoreRefused


class Store:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.puts = []
        self.deletes = []

    def digest(self, bucket, key):
        value = self.values.get((bucket, key))
        return (
            (len(value), hashlib.sha256(value).hexdigest())
            if value is not None else None
        )

    def put(self, entry, payload):
        self.puts.append((entry.bucket, entry.key))
        self.values[(entry.bucket, entry.key)] = payload

    def delete(self, bucket, key):
        self.deletes.append((bucket, key))
        self.values.pop((bucket, key))


class Artifact:
    def __init__(self, payload):
        self.payload = payload
        self.reads = 0

    def object_bytes(self, _entry):
        self.reads += 1
        return self.payload


def item(payload=b"portable object"):
    return ObjectEntry(
        "private", "imports/run/object", hashlib.sha256(payload).hexdigest(),
        len(payload), "objects/one",
    )


def ledger(tmp_path):
    return RunLedger(
        tmp_path / "run.jsonl", run_id=uuid.uuid4(), artifact_sha256="a" * 64
    )


class StorageAccount:
    def __init__(self):
        self.storage_bytes_used = 0

    def refresh_from_db(self, *, fields):
        assert fields == ("storage_bytes_used",)


@pytest.fixture
def storage_account(monkeypatch):
    account = StorageAccount()

    def add_storage(makerspace, size):
        assert makerspace is account
        makerspace.storage_bytes_used += size

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_restore_objects.limits.add_storage",
        add_storage,
    )
    return account


def test_equal_existing_bytes_are_accepted_without_write_and_never_rolled_back(
    tmp_path, storage_account,
):
    entry = item()
    store = Store({(entry.bucket, entry.key): b"portable object"})
    run = ledger(tmp_path)

    assert load_object(
        run, store, Artifact(b"portable object"), entry,
        index=0, makerspace=storage_account,
    ) == "accepted_existing"
    assert storage_account.storage_bytes_used == len(b"portable object")
    assert rollback_created_objects(run, store) == ()
    assert store.deletes == []


def test_created_bytes_are_rollback_owned_and_completed_resume_skips_write(
    tmp_path, storage_account,
):
    entry = item()
    store = Store()
    artifact = Artifact(b"portable object")
    run = ledger(tmp_path)

    assert load_object(
        run, store, artifact, entry, index=0, makerspace=storage_account
    ) == "created_by_this_run"
    assert storage_account.storage_bytes_used == len(b"portable object")
    assert artifact.reads == 1
    # Completed effects are skipped by the ordered command; direct rollback owns only
    # the entry whose pre-write outcome says this run created it.
    assert rollback_created_objects(run, store) == ((entry.bucket, entry.key),)


def test_created_outcome_is_fsynced_to_the_ledger_before_object_write(
    tmp_path, storage_account,
):
    entry = item()
    run = ledger(tmp_path)

    class OrderedStore(Store):
        def put(self, entry, payload):
            current = run.records()[-1]
            assert current["state"] == "begun"
            assert current["detail"] == {
                "bucket": entry.bucket,
                "key": entry.key,
                "digest": entry.sha256,
                "outcome": "created_by_this_run",
                "accepted_size": len(b"portable object"),
            }
            super().put(entry, payload)

    load_object(
        run, OrderedStore(), Artifact(b"portable object"), entry,
        index=0, makerspace=storage_account,
    )


def test_existing_bytes_require_sha256_equality(tmp_path, storage_account):
    entry = item()
    store = Store({(entry.bucket, entry.key): b"substitution"})
    with pytest.raises(TenantRestoreRefused, match="different SHA-256"):
        load_object(
            ledger(tmp_path), store, Artifact(b"portable object"), entry,
            index=0, makerspace=storage_account,
        )


def test_crash_after_write_resumes_without_rewriting_and_keeps_created_outcome(
    tmp_path, storage_account,
):
    entry = item()
    run = ledger(tmp_path)
    begun = run.begin(
        "object-load-000000-" + entry.sha256[:12],
        {"bucket": entry.bucket, "key": entry.key, "digest": entry.sha256,
         "outcome": "created_by_this_run", "accepted_size": len(b"portable object")},
    )
    assert begun["state"] == "begun"
    store = Store({(entry.bucket, entry.key): b"portable object"})
    artifact = Artifact(b"portable object")

    assert load_object(
        run, store, artifact, entry, index=0, makerspace=storage_account
    ) == "created_by_this_run"
    assert artifact.reads == 0
    assert store.puts == []


def test_retry_after_charge_before_ledger_finish_does_not_double_count(
    tmp_path, storage_account,
):
    entry = item()
    run = ledger(tmp_path)
    store = Store()
    real_finish = run.finish
    calls = 0

    def fail_first_finish(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("crash after charge")
        return real_finish(*args, **kwargs)

    run.finish = fail_first_finish
    with pytest.raises(RuntimeError, match="crash after charge"):
        load_object(
            run, store, Artifact(b"portable object"), entry,
            index=0, makerspace=storage_account,
        )
    assert storage_account.storage_bytes_used == len(b"portable object")

    assert load_object(
        run, store, Artifact(b"portable object"), entry,
        index=0, makerspace=storage_account,
    ) == "created_by_this_run"
    assert storage_account.storage_bytes_used == len(b"portable object")


def test_partial_restore_charges_only_the_newly_accepted_delta(
    tmp_path, storage_account,
):
    first_payload = b"first accepted object"
    second_payload = b"second accepted object"
    first = item(first_payload)
    second = ObjectEntry(
        first.bucket, "imports/run/two", hashlib.sha256(second_payload).hexdigest(),
        len(second_payload), "objects/two",
    )
    run = ledger(tmp_path)
    store = Store()

    load_object(
        run, store, Artifact(first_payload), first,
        index=0, makerspace=storage_account,
    )
    assert storage_account.storage_bytes_used == len(first_payload)

    load_object(
        run, store, Artifact(second_payload), second,
        index=1, makerspace=storage_account,
    )
    assert storage_account.storage_bytes_used == len(first_payload) + len(second_payload)


def test_charge_uses_observed_bytes_not_declared_size(tmp_path, storage_account):
    payload = b"actual accepted bytes"
    entry = item(payload)
    entry = ObjectEntry(
        entry.bucket, entry.key, entry.sha256, entry.size + 1000, entry.member
    )
    store = Store({(entry.bucket, entry.key): payload})

    assert load_object(
        ledger(tmp_path), store, Artifact(payload), entry,
        index=0, makerspace=storage_account,
    ) == "accepted_existing"
    assert storage_account.storage_bytes_used == len(payload)
