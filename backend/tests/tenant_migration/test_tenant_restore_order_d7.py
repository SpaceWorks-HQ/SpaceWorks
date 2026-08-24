from dataclasses import replace
import uuid

import pytest

from apps.backup.host_run_ledger import RunLedger
from apps.backup.host_supervisor import HostMarkerTransition
from apps.backup.operation_lock import OperationLockUnavailable, host_operation_lock
from apps.tenant_migration.tenant_restore_orchestrator import run_target_restore
from apps.tenant_migration.tenant_restore_types import (
    ArtifactPreflight,
    PrivilegeFacts,
    ResourceIdentity,
    RestoreInputs,
    SiblingPlan,
    SiblingResource,
    TenantRestoreRefused,
    TopologyPreflight,
)


ARTIFACT = "a" * 64
class Artifact:
    def static_preflight(self, _inputs):
        return ArtifactPreflight(*([True] * 12))

    def database_dump_path(self):
        return "/artifact/database.dump"
class Writers:
    def __init__(self, events, ops):
        self.events = events
        self.ops = ops
        self.excluded = False
        self.gates_cleared = False

    def persist_offline(self, _inputs, _preflight):
        self.events.append("offline")
        return {"marker": "fsynced"}

    def exclude_image_writers(self, writers):
        self.events.append("exclude")
        self.excluded = set(writers) == {"backend", "worker"}
        return {"writers": list(writers)}

    def prove_image_writers_excluded(self, _writers):
        return self.excluded

    def clear_gates(self, _sibling):
        self.events.append("clear-host-gate")
        self.gates_cleared = True
        return {"marker_removed": True}

    def start(self, _sibling, generation):
        assert self.gates_cleared
        self.events.append("start")
        with pytest.raises(OperationLockUnavailable):
            with host_operation_lock(self.ops, require_root_owned=False):
                pass
        return {"generation": generation, "marker_observed": True}


class Database:
    def __init__(self, writers, events, *, fail_restore_once=False):
        self.writers = writers
        self.events = events
        self.fail_restore_once = fail_restore_once
        self.serial = 0
        self.last = None
        self.cleaned = []

    def privilege_facts(self):
        return PrivilegeFacts(True, True, True, True, True, True)

    def source_identity(self):
        return ResourceIdentity("source:5432", "source", "source-uuid", 10)

    def scratch_identity(self):
        return ResourceIdentity("scratch:5432", "scratch", "scratch-uuid", 11)

    def sibling_plan(self):
        return SiblingPlan(False, True, True, "candidate")

    def allocate(self, *, fresh_after_interrupted_restore):
        assert self.writers.excluded
        if self.last is None or fresh_after_interrupted_restore:
            self.serial += 1
            identity = ResourceIdentity(
                "target:5432", f"candidate_{self.serial}", "", 100 + self.serial
            )
            self.last = SiblingResource(
                identity, f"postgres:///{identity.database_name}", False, True, True,
                f"owner-{self.serial}",
            )
        self.events.append(f"allocate-{self.serial}")
        return self.last

    def prove_sibling(self, sibling):
        return replace(sibling, empty=True)

    def recover_sibling(self, _expected):
        return replace(self.last, empty=True)

    def restore(self, _sibling, _dump):
        self.events.append("restore")
        if self.fail_restore_once:
            self.fail_restore_once = False
            raise RuntimeError("crash during pg_restore")

    def apply_runtime_ownership_and_grants(self, _sibling):
        self.events.append("grants")

    def cleanup(self, sibling, *, successful):
        self.cleaned.append((sibling.identity.database_name, successful))
        self.last = None
        return {"cleaned": sibling.identity.database_name}

    def database_marker_matches(self, _sibling, expected):
        return expected == {"database_uuid": "target-uuid", "run_id": RUN_ID,
                            "artifact_sha256": ARTIFACT, "capture_id": CAPTURE_ID}


class Pointer:
    def __init__(self, events):
        self.events = events
        self.swapped = False

    def preflight(self, *, allow_committed_cutover=False):
        return TopologyPreflight(
            True, True, ResourceIdentity("target:5432", "active", "active-uuid", 1),
            "image", True, True, ("backend", "worker"),
        )

    def current_generation(self):
        return 1

    def cutover_detail(self, _sibling):
        return {
            "old_generation": 1, "new_generation": 2,
            "new_database_url": "postgres:///candidate",
            "new_database_marker": {
                "database_uuid": "target-uuid", "run_id": RUN_ID,
                "artifact_sha256": ARTIFACT, "capture_id": CAPTURE_ID,
            },
        }

    def compare_and_swap(self, _detail):
        self.events.append("cutover")
        self.swapped = True

    def record_matches(self, _detail):
        return self.swapped


class Target:
    def __init__(self, pointer, events):
        self.pointer = pointer
        self.events = events

    def establish(self, _sibling, _inputs):
        self.events.append("target-import")
        return {"mode": "target_import"}

    def reissue_api_clients(self, _sibling, _inputs):
        return {"count": 0}

    def create_superadmin(self, _sibling, _inputs):
        return {"created": True}

    def verify_activation(self, _sibling, _inputs):
        return {"verified": True}

    def set_normal(self, _sibling):
        assert self.pointer.swapped
        self.events.append("normal")
        return {"mode": "normal"}


class Objects:
    def reserve_prefix(self, prefix):
        return {"prefix": prefix}


class Journal:
    def invalidate_all(self, _reason):
        return 1


RUN_ID = str(uuid.uuid4())
CAPTURE_ID = str(uuid.uuid4())

def invoke(tmp_path, database):
    pointer = Pointer(database.events)
    return run_target_restore(
        ops_dir=tmp_path / "ops",
        inputs=RestoreInputs(RUN_ID, ARTIFACT, CAPTURE_ID, "admin@example.test"),
        artifact=Artifact(), database=database, writers=database.writers,
        pointer=pointer, target=Target(pointer, database.events),
        object_store=Objects(), destination_prefix="imports/run",
        capability_journal=Journal(), marker_writer=HostMarkerTransition(tmp_path / "marker.json", Journal(), require_root_owned=False),
        require_root_owned=False,
    )


def test_static_refusal_creates_no_target_state_or_sibling(tmp_path):
    events = []
    writers = Writers(events, tmp_path / "ops")
    database = Database(writers, events)

    class InvalidArtifact(Artifact):
        def static_preflight(self, _inputs):
            facts = [True] * 12
            facts[0] = False
            return ArtifactPreflight(*facts)

    pointer = Pointer(events)
    with pytest.raises(TenantRestoreRefused, match="digest"):
        run_target_restore(
            ops_dir=tmp_path / "ops",
            inputs=RestoreInputs(RUN_ID, ARTIFACT, CAPTURE_ID, "admin@example.test"),
            artifact=InvalidArtifact(), database=database, writers=writers,
            pointer=pointer, target=Target(pointer, events), object_store=Objects(),
            destination_prefix="imports/run", capability_journal=Journal(),
            marker_writer=HostMarkerTransition(tmp_path / "marker.json", Journal(), require_root_owned=False),
            require_root_owned=False,
        )
    assert events == []
    assert not (tmp_path / "ops" / "runs" / f"{RUN_ID}.jsonl").exists()


def test_ordered_command_keeps_exclusion_and_lock_through_final_record(tmp_path):
    events = []
    writers = Writers(events, tmp_path / "ops")
    database = Database(writers, events)

    invoke(tmp_path, database)

    assert events.index("exclude") < events.index("allocate-1")
    assert events.index("cutover") < events.index("normal")
    assert events.index("normal") < events.index("clear-host-gate") < events.index("start")
    ledger = RunLedger(
        tmp_path / "ops" / "runs" / f"{RUN_ID}.jsonl",
        run_id=RUN_ID, artifact_sha256=ARTIFACT,
    )
    final = [item for item in ledger.records() if item["phase"] == "finalize"][-1]
    assert final["state"] == "done"
    assert final["detail"]["lock_still_held"] is True
    with host_operation_lock(tmp_path / "ops", require_root_owned=False):
        pass


def test_interrupted_pg_restore_reprovisions_a_distinct_empty_sibling(tmp_path):
    events = []
    writers = Writers(events, tmp_path / "ops")
    database = Database(writers, events, fail_restore_once=True)

    with pytest.raises(RuntimeError, match="crash during pg_restore"):
        invoke(tmp_path, database)
    invoke(tmp_path, database)

    assert database.cleaned == [("candidate_1", False)]
    assert "allocate-2" in events
    ledger = RunLedger(
        tmp_path / "ops" / "runs" / f"{RUN_ID}.jsonl",
        run_id=RUN_ID, artifact_sha256=ARTIFACT,
    )
    begun = [
        row for row in ledger.records()
        if row["phase"] == "database-restore" and row["state"] == "begun"
    ]
    assert begun[0]["detail"]["sibling"]["identity"] != begun[1]["detail"]["sibling"]["identity"]


def test_interrupted_restore_accepts_only_a_fresh_operator_supplied_sibling(tmp_path):
    events = []
    writers = Writers(events, tmp_path / "ops")

    class SuppliedDatabase(Database):
        def sibling_plan(self):
            return SiblingPlan(True, True, True, "operator_candidate")

        def allocate(self, *, fresh_after_interrupted_restore):
            assert not fresh_after_interrupted_restore
            assert self.writers.excluded
            return self.last

    database = SuppliedDatabase(writers, events, fail_restore_once=True)
    first_identity = ResourceIdentity("target:5432", "operator_one", "", 201)
    database.last = SiblingResource(
        first_identity, "postgres:///operator_one", False, True, False
    )
    with pytest.raises(RuntimeError, match="crash during pg_restore"):
        invoke(tmp_path, database)

    second_identity = ResourceIdentity("target:5432", "operator_two", "", 202)
    database.last = SiblingResource(
        second_identity, "postgres:///operator_two", False, True, False
    )
    invoke(tmp_path, database)

    assert database.cleaned == []
