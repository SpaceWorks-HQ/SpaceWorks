import fcntl
import os
import uuid

import pytest

from apps.backup.host_run_ledger import RunLedger, RunLedgerError
from apps.backup.host_supervisor import SupervisorSession, supervise_run
from apps.backup.operation_lock import OperationLockUnavailable, host_operation_lock


ARTIFACT = "a" * 64
PHASES = ("preflight", "database-restore", "pointer-cutover")


def _ledger(tmp_path):
    return RunLedger(
        tmp_path / "run.jsonl",
        run_id=uuid.uuid4(),
        artifact_sha256=ARTIFACT,
    )


def test_effect_records_begun_before_and_done_after_the_effect(tmp_path):
    ledger = _ledger(tmp_path)

    with ledger.effect("preflight", {"input": "verified"}):
        records = ledger.records()
        assert [item["state"] for item in records] == ["begun"]
        assert records[0]["finished_at"] is None

    records = ledger.records()
    assert [item["state"] for item in records] == ["begun", "done"]
    assert records[1]["finished_at"] is not None
    assert set(records[0]) == {
        "run_id", "artifact_sha256", "phase", "state", "attempt",
        "started_at", "finished_at", "detail",
    }


def test_resume_enters_first_phase_without_done(tmp_path):
    ledger = _ledger(tmp_path)
    with ledger.effect("preflight", {}):
        pass

    assert ledger.resume_decision(PHASES).phase == "database-restore"


def test_interrupted_database_restore_requires_new_empty_sibling(tmp_path):
    ledger = _ledger(tmp_path)
    # Resume enters the FIRST phase lacking `done`, so preflight must be completed before this
    # test can say anything about database-restore; without it resume correctly returns preflight.
    with ledger.effect("preflight", {}):
        pass
    ledger.begin(
        "database-restore",
        {"sibling": {"identity": "candidate-one", "empty": True}},
    )
    decision = ledger.resume_decision(PHASES)

    assert decision.requires_new_empty_sibling is True
    assert decision.attempt == 2
    for detail in (
        {"sibling": {"identity": "candidate-one", "empty": True}},
        {"sibling": {"identity": "candidate-two", "empty": False}},
        {},
    ):
        with pytest.raises(RunLedgerError, match="new empty sibling"):
            ledger.begin("database-restore", detail)

    begun = ledger.begin(
        "database-restore",
        {"sibling": {"identity": "candidate-two", "empty": True}},
    )
    assert begun["attempt"] == 2


def test_supervisor_holds_global_lock_before_ledger_read_until_exit(tmp_path):
    ops = tmp_path / "ops"
    with supervise_run(
        ops,
        run_id=uuid.uuid4(),
        artifact_sha256=ARTIFACT,
        phases=PHASES,
        require_root_owned=False,
    ) as session:
        flags = fcntl.fcntl(session.lock_handle.fileno(), fcntl.F_GETFD)
        assert flags & fcntl.FD_CLOEXEC
        with pytest.raises(OperationLockUnavailable):
            with host_operation_lock(ops, require_root_owned=False):
                pass

    with host_operation_lock(ops, require_root_owned=False):
        pass


def test_docker_process_cannot_inherit_supervisor_lock_descriptor(tmp_path):
    with host_operation_lock(tmp_path, require_root_owned=False) as handle:
        assert os.get_inheritable(handle.fileno()) is False


def test_terminal_supervisor_state_invalidates_launch_authority():
    observed = []
    journal = type("Journal", (), {
        "invalidate_all": lambda _self, reason: observed.append(reason) or 2
    })()

    assert SupervisorSession(None, None, None).terminal(journal) == 2
    assert observed == ["terminal-operation"]
