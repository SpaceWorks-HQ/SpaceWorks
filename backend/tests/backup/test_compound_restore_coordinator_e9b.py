import pytest
import uuid

from apps.backup.compound_restore_coordinator import run_compound_restore
from apps.backup.compound_restore_rollback import rollback_compound_restore
from apps.backup.compound_restore_preflight import _validate_topology
from apps.backup.compound_restore_types import (
    CompoundRestoreRefused,
    CompoundTopologyFacts,
)
from apps.backup.host_marker import (
    DatabaseIdentity,
    MarkerError,
    MarkerState,
    OperationIdentity,
    read_marker,
)
from apps.backup.host_run_ledger import RunLedger
from apps.backup.host_supervisor import HostMarkerTransition
from apps.backup.host_pointer import PointerRecord, read_pointer, write_pointer_atomic
from apps.backup.compound_restore_pointer import FileCompoundPointer
from apps.tenant_migration.tenant_restore_types import ResourceIdentity, SiblingResource
from tests.backup.e9b_coordinator_test_support import (
    ARTIFACT,
    RUN,
    inputs,
    invoke,
)


def test_pre_cutover_state_and_acknowledgement_order(monkeypatch, tmp_path):
    arguments, events, pointer, _database = invoke(monkeypatch, tmp_path)
    run_compound_restore(**arguments)

    assert events.index("not-restored-and-reservations") < events.index("pointer-cutover")
    assert events.index("fences-installed") < events.index("pointer-cutover")
    assert events.index("candidate-backend-without-migrate") < events.index("pointer-cutover")
    assert events.index("acknowledgement") < events.index("marker:normal")
    assert events.index("marker:normal") < events.index("start:backend,worker,beat")
    assert pointer.current == "new"

    ledger = RunLedger(
        tmp_path / "ops" / "runs" / f"{RUN}.jsonl",
        run_id=RUN, artifact_sha256=ARTIFACT,
    )
    cutover = next(
        row["detail"] for row in ledger.records()
        if row["phase"] == "cutover" and row["state"] == "done"
    )
    assert cutover["old_database_url"].endswith("/active")
    assert cutover["new_database_url"].endswith("/candidate")
    assert cutover["sibling_ownership_proof"]["owner_marker"]
    assert cutover["grant_state"]["state"] == "candidate-preparation"
    assert cutover["object_effects"][0]["outcome"] == "created_by_this_run"


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_cutover_crash_resumes_at_each_pointer_boundary(
    boundary, monkeypatch, tmp_path
):
    arguments, _events, pointer, _database = invoke(
        monkeypatch, tmp_path, crash=boundary
    )
    with pytest.raises(RuntimeError, match=f"crash {boundary} pointer"):
        run_compound_restore(**arguments)
    run_compound_restore(**arguments)
    assert pointer.current == "new"


def test_rollback_reverses_pointer_and_objects_but_keeps_owner_proof(
    monkeypatch, tmp_path
):
    arguments, events, pointer, database = invoke(monkeypatch, tmp_path)
    run_compound_restore(**arguments)
    detail = rollback_compound_restore(
        ops_dir=tmp_path / "ops", inputs=inputs(), pointer=pointer,
        database=database, object_store=arguments["object_store"],
        require_root_owned=False,
    )

    assert pointer.current == "old"
    assert events.index("pointer-rollback") < events.index("object-rollback")
    assert detail["candidate_retained"] is True
    assert detail["sibling_ownership_proof"]["owner_marker"]
    assert len(detail["reversed_object_effects"]) == 1
    assert detail["reversed_object_effects"][0]["key"] == "main/x"


def test_rollback_refuses_to_drop_unowned_candidate_before_reversal(
    monkeypatch, tmp_path
):
    arguments, events, pointer, database = invoke(monkeypatch, tmp_path)
    run_compound_restore(**arguments)
    database.owned = False

    with pytest.raises(CompoundRestoreRefused, match="unowned"):
        rollback_compound_restore(
            ops_dir=tmp_path / "ops", inputs=inputs(), pointer=pointer,
            database=database, object_store=arguments["object_store"],
            require_root_owned=False, drop_candidate=True,
        )
    assert pointer.current == "new"
    assert "object-rollback" not in events


def test_external_database_url_without_journalled_swap_is_refused():
    with pytest.raises(CompoundRestoreRefused, match="external authoritative"):
        _validate_topology(CompoundTopologyFacts(
            "external-orchestrator", True, True, True, True, True,
            ("backend", "worker"), authoritative_database_url="external",
            external_journalled_swap=False,
        ))


def test_supervisor_enriches_only_the_same_bound_database_in_order(tmp_path):
    journal = type("Journal", (), {"invalidate_all": lambda *_args: 1})()
    marker_path = tmp_path / "marker.json"
    transition = HostMarkerTransition(
        marker_path, journal, require_root_owned=False
    )
    operation = OperationIdentity(RUN, ARTIFACT, inputs().capture_id, 1)
    basic = DatabaseIdentity("candidate", 42)
    transition.write_intent(operation)
    transition.bind_database(basic, operation)

    with pytest.raises(MarkerError, match="out of order"):
        transition.transition_bound(MarkerState.NORMAL, basic, operation)

    enriched = DatabaseIdentity("candidate", 42, {
        "endpoint": {
            "host": "db", "port": 5432, "database": "candidate",
            "tls_identity": "",
        },
        "database_uuid": str(uuid.uuid4()),
        "system_identifier": None,
    })
    transition.transition_bound(
        MarkerState.CANDIDATE_HEALTH, enriched, operation
    )
    assert read_marker(
        marker_path, require_root_owned=False
    ).require_bound_database() == enriched


def test_preflight_refusal_has_no_pointer_env_object_or_restart_mutation(
    monkeypatch, tmp_path
):
    arguments, events, pointer, _database = invoke(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "apps.backup.compound_restore_coordinator.validate_compound_preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CompoundRestoreRefused("outer digest refused")
        ),
    )

    with pytest.raises(CompoundRestoreRefused, match="outer digest"):
        run_compound_restore(**arguments)

    assert pointer.current == "old"  # no pointer move
    assert events == []  # no env write, object write, or process restart adapter
    assert not (
        tmp_path / "ops" / "runs" / f"{RUN}.jsonl"
    ).exists()
    assert not (tmp_path / "marker.json").exists()


@pytest.mark.parametrize(
    ("adapter_name", "effect_name"),
    (
        ("writers", "persist_offline"),
        ("writers", "exclude"),
        ("database", "allocate"),
        ("database", "prove_sibling"),
        ("database", "restore"),
        ("database", "apply_runtime_ownership_and_grants"),
        ("target", "rehydrate"),
        ("target", "install_enforcement"),
        ("target", "verify_catalog"),
        ("object_store", "restore_main"),
        ("target", "prepare_quarantine"),
        ("target", "verify_quarantine"),
        ("database", "apply_grant_state"),
        ("target", "acknowledge_recovery"),
        ("writers", "start_normal"),
    ),
)
def test_pre_cutover_journal_boundary_resumes_idempotently(
    adapter_name, effect_name, monkeypatch, tmp_path
):
    arguments, _events, pointer, _database = invoke(monkeypatch, tmp_path)
    adapter = arguments[adapter_name]
    original = getattr(adapter, effect_name)
    first = True

    def crash_once(*args, **kwargs):
        nonlocal first
        result = original(*args, **kwargs)
        if first:
            first = False
            raise RuntimeError(f"crash after {effect_name}")
        return result

    monkeypatch.setattr(adapter, effect_name, crash_once)
    with pytest.raises(RuntimeError, match=f"crash after {effect_name}"):
        run_compound_restore(**arguments)
    run_compound_restore(**arguments)
    assert pointer.current == "new"


@pytest.mark.parametrize("boundary", ["rollback-before", "rollback-after"])
def test_rollback_resumes_at_each_pointer_boundary(
    boundary, monkeypatch, tmp_path
):
    arguments, _events, pointer, database = invoke(monkeypatch, tmp_path)
    run_compound_restore(**arguments)
    pointer.crash = boundary
    with pytest.raises(RuntimeError, match="rollback pointer"):
        rollback_compound_restore(
            ops_dir=tmp_path / "ops", inputs=inputs(), pointer=pointer,
            database=database, object_store=arguments["object_store"],
            require_root_owned=False,
        )
    rollback_compound_restore(
        ops_dir=tmp_path / "ops", inputs=inputs(), pointer=pointer,
        database=database, object_store=arguments["object_store"],
        require_root_owned=False,
    )
    assert pointer.current == "old"


def test_rollback_resumes_between_pointer_and_object_reversal(
    monkeypatch, tmp_path
):
    arguments, _events, pointer, database = invoke(monkeypatch, tmp_path)
    run_compound_restore(**arguments)
    object_store = arguments["object_store"]
    original = object_store.rollback
    first = True

    def crash_once(effects):
        nonlocal first
        result = original(effects)
        if first:
            first = False
            raise RuntimeError("crash after object reversal")
        return result

    monkeypatch.setattr(object_store, "rollback", crash_once)
    with pytest.raises(RuntimeError, match="crash after object reversal"):
        rollback_compound_restore(
            ops_dir=tmp_path / "ops", inputs=inputs(), pointer=pointer,
            database=database, object_store=object_store,
            require_root_owned=False,
        )
    assert pointer.current == "old"
    rollback_compound_restore(
        ops_dir=tmp_path / "ops", inputs=inputs(), pointer=pointer,
        database=database, object_store=object_store,
        require_root_owned=False,
    )


def test_file_pointer_cutover_and_rollback_use_atomic_monotonic_records(tmp_path):
    path = tmp_path / "database-pointer.env"
    write_pointer_atomic(
        path, PointerRecord("postgres://app@db/active", 1),
        require_root_owned=False,
    )
    topology = CompoundTopologyFacts(
        "bundled-compose", True, True, True, True, True,
        ("backend", "worker", "beat"),
    )
    identity = ResourceIdentity("db:5432", "active", str(uuid.uuid4()), 1)
    sibling_identity = ResourceIdentity(
        "db:5432", "candidate", str(uuid.uuid4()), 2
    )
    sibling = SiblingResource(
        sibling_identity, "postgres://owner@db/candidate", True, True, True,
        "owner-proof",
    )
    adapter = FileCompoundPointer(
        path=path, topology=topology, current_identity=lambda: identity,
        runtime_url=lambda _sibling: "postgres://app@db/candidate",
        invalidate_capabilities=lambda _reason: None,
        require_root_owned=False,
    )

    detail = adapter.cutover_detail(sibling)
    adapter.compare_and_swap(detail)
    assert adapter.record_matches(detail)
    adapter.rollback(detail)
    assert adapter.record_matches(detail, rolled_back=True)
    assert read_pointer(path, require_root_owned=False) == PointerRecord(
        "postgres://app@db/active", 3
    )
