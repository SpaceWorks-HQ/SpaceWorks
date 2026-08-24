import uuid

import pytest

from apps.backup.host_pointer import PointerRecord, VersionedPointer
from apps.backup.host_run_ledger import RunLedger
from apps.tenant_migration.tenant_restore_activation import cutover
from apps.tenant_migration.tenant_restore_pointer import ExternalPointerAdapter
from apps.tenant_migration.tenant_restore_types import ResourceIdentity, TenantRestoreRefused


class Pointer:
    def __init__(self, crash):
        self.committed = False
        self.crash = crash

    def cutover_detail(self, _sibling):
        return {
            "old_generation": 4,
            "new_generation": 5,
            "new_database_marker": {"database_uuid": "new"},
        }

    def compare_and_swap(self, _detail):
        if self.crash == "before":
            self.crash = None
            raise RuntimeError("before rename")
        self.committed = True
        if self.crash == "after":
            self.crash = None
            raise RuntimeError("after rename")

    def record_matches(self, _detail):
        return self.committed


class Database:
    marker_matches = True

    def database_marker_matches(self, _sibling, _expected):
        return self.marker_matches


def ledger(tmp_path):
    return RunLedger(
        tmp_path / "run.jsonl",
        run_id=uuid.uuid4(),
        artifact_sha256="a" * 64,
    )


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_cutover_crash_reentry_requires_pointer_and_marker(boundary, tmp_path):
    run = ledger(tmp_path)
    pointer = Pointer(boundary)
    database = Database()
    with pytest.raises(RuntimeError, match=f"{boundary} rename"):
        cutover(run, pointer, database, object())

    detail = cutover(run, pointer, database, object())

    assert detail["new_generation"] == 5
    assert [row["state"] for row in run.records()][-1] == "done"


def test_completed_cutover_refuses_when_database_marker_no_longer_matches(tmp_path):
    run = ledger(tmp_path)
    pointer = Pointer(None)
    database = Database()
    cutover(run, pointer, database, object())
    database.marker_matches = False

    with pytest.raises(TenantRestoreRefused, match="pointer or marker changed"):
        cutover(run, pointer, database, object())


def test_external_pointer_preflight_refuses_a_stale_expected_store_version():
    class Store:
        supports_compare_and_swap = True

        def read(self):
            return VersionedPointer(PointerRecord("postgres:///active", 3), "v3")

    pointer = ExternalPointerAdapter(
        store=Store(), expected_version="v2",
        current_identity=lambda: ResourceIdentity("db:5432", "active", "uuid", 1),
        marker_reader=lambda _sibling: {}, runtime_url=lambda _sibling: "",
        invalidate_capabilities=lambda _reason: None, scheduler_mode="external",
        complete_writer_set=("backend",),
    )

    with pytest.raises(TenantRestoreRefused, match="stale"):
        pointer.preflight()
