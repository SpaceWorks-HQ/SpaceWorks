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
        return hashlib.sha256(value).hexdigest() if value is not None else None

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


def test_equal_existing_bytes_are_accepted_without_write_and_never_rolled_back(tmp_path):
    entry = item()
    store = Store({(entry.bucket, entry.key): b"portable object"})
    run = ledger(tmp_path)

    assert load_object(run, store, Artifact(b"portable object"), entry, index=0) == "accepted_existing"
    assert rollback_created_objects(run, store) == ()
    assert store.deletes == []


def test_created_bytes_are_rollback_owned_and_completed_resume_skips_write(tmp_path):
    entry = item()
    store = Store()
    artifact = Artifact(b"portable object")
    run = ledger(tmp_path)

    assert load_object(run, store, artifact, entry, index=0) == "created_by_this_run"
    assert artifact.reads == 1
    # Completed effects are skipped by the ordered command; direct rollback owns only
    # the entry whose pre-write outcome says this run created it.
    assert rollback_created_objects(run, store) == ((entry.bucket, entry.key),)


def test_created_outcome_is_fsynced_to_the_ledger_before_object_write(tmp_path):
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
            }
            super().put(entry, payload)

    load_object(run, OrderedStore(), Artifact(b"portable object"), entry, index=0)


def test_existing_bytes_require_sha256_equality(tmp_path):
    entry = item()
    store = Store({(entry.bucket, entry.key): b"substitution"})
    with pytest.raises(TenantRestoreRefused, match="different SHA-256"):
        load_object(ledger(tmp_path), store, Artifact(b"portable object"), entry, index=0)


def test_crash_after_write_resumes_without_rewriting_and_keeps_created_outcome(tmp_path):
    entry = item()
    run = ledger(tmp_path)
    begun = run.begin(
        "object-load-000000-" + entry.sha256[:12],
        {"bucket": entry.bucket, "key": entry.key, "digest": entry.sha256,
         "outcome": "created_by_this_run"},
    )
    assert begun["state"] == "begun"
    store = Store({(entry.bucket, entry.key): b"portable object"})
    artifact = Artifact(b"portable object")

    assert load_object(run, store, artifact, entry, index=0) == "created_by_this_run"
    assert artifact.reads == 0
    assert store.puts == []
