from apps.backup.host_marker import MarkerStage, read_marker
from apps.backup.host_supervisor import HostMarkerTransition
from apps.tenant_migration.tenant_restore_orchestrator import run_target_restore
from apps.tenant_migration.tenant_restore_types import (
    ResourceIdentity,
    RestoreInputs,
    SiblingResource,
)
from tests.tenant_migration.test_tenant_restore_order_d7 import (
    ARTIFACT,
    CAPTURE_ID,
    RUN_ID,
    Artifact,
    Database,
    Journal,
    Objects,
    Pointer,
    Target,
    Writers,
)

import pytest


class CrashAfterIntent:
    def __init__(self, transition):
        self.transition = transition
        self.crashed = False

    def write_intent(self, operation):
        result = self.transition.write_intent(operation)
        if not self.crashed:
            self.crashed = True
            raise RuntimeError("simulated crash after intent")
        return result

    def bind_database(self, database, operation):
        return self.transition.bind_database(database, operation)


class CrashAfterBoundRename:
    def __init__(self, marker_path, journal):
        self.transition = HostMarkerTransition(
            marker_path, journal, require_root_owned=False
        )
        self.marker_path = marker_path
        self.journal = journal

    def write_intent(self, operation):
        return self.transition.write_intent(operation)

    def bind_database(self, database, operation):
        def crash(stage):
            if stage == "before_parent_fsync":
                raise RuntimeError("simulated crash after bound rename")

        return HostMarkerTransition(
            self.marker_path,
            self.journal,
            require_root_owned=False,
            crash_hook=crash,
        ).bind_database(database, operation)


def _run(tmp_path, database, marker_writer):
    pointer = Pointer(database.events)
    return run_target_restore(
        ops_dir=tmp_path / "ops",
        inputs=RestoreInputs(RUN_ID, ARTIFACT, CAPTURE_ID, "admin@example.test"),
        artifact=Artifact(),
        database=database,
        writers=database.writers,
        pointer=pointer,
        target=Target(pointer, database.events),
        object_store=Objects(),
        destination_prefix="imports/run",
        capability_journal=Journal(),
        marker_writer=marker_writer,
        require_root_owned=False,
    )


def test_resume_after_intent_demands_new_empty_sibling_and_never_adopts_name(
    tmp_path,
):
    events = []
    writers = Writers(events, tmp_path / "ops")
    database = Database(writers, events)
    marker_path = tmp_path / "marker.json"
    transition = HostMarkerTransition(
        marker_path, Journal(), require_root_owned=False
    )
    crash_once = CrashAfterIntent(transition)

    with pytest.raises(RuntimeError, match="crash after intent"):
        _run(tmp_path, database, crash_once)

    intent = read_marker(marker_path, require_root_owned=False)
    assert intent.stage == MarkerStage.INTENT
    assert intent.database is None

    # A name match is not identity proof. Simulate a database appearing under the
    # planned name while the host was down; the resumed attempt must replace it.
    matching = ResourceIdentity("target:5432", "candidate", "", 101)
    database.last = SiblingResource(
        matching, "postgres:///candidate", True, True, True, "owner-1"
    )
    database.serial = 1

    _run(tmp_path, database, transition)

    assert database.last.identity.database_name == "candidate_2"
    assert database.last.identity.database_oid == 102
    assert "allocate-2" in events
    bound = read_marker(marker_path, require_root_owned=False)
    assert bound.stage == MarkerStage.BOUND
    assert bound.require_bound_database().name == "candidate_2"


def test_resume_after_bound_rename_still_replaces_the_interrupted_sibling(tmp_path):
    events = []
    writers = Writers(events, tmp_path / "ops")
    database = Database(writers, events)
    marker_path = tmp_path / "marker.json"
    journal = Journal()

    with pytest.raises(RuntimeError, match="crash after bound rename"):
        _run(tmp_path, database, CrashAfterBoundRename(marker_path, journal))

    renamed = read_marker(marker_path, require_root_owned=False)
    assert renamed.stage == MarkerStage.BOUND
    assert renamed.require_bound_database().name == "candidate_1"

    _run(
        tmp_path,
        database,
        HostMarkerTransition(marker_path, journal, require_root_owned=False),
    )

    assert database.last.identity.database_name == "candidate_2"
    assert database.last.identity.database_oid == 102
    rebound = read_marker(marker_path, require_root_owned=False)
    assert rebound.require_bound_database().name == "candidate_2"
