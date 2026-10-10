"""Genesis membership stays bounded without losing cutover tamper detection."""

from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit import services as audit
from apps.audit import verification_runs as runs
from apps.audit.batch_format import genesis_entry
from apps.audit.batch_verification import AuditFailureClass
from apps.audit.integrity_rows import GenesisMembershipLimitExceeded, _verify_genesis_membership
from apps.audit.models import AuditLog, AuditVerificationRunEvent
from apps.audit.verification_execution import execute_attempt
from tests.audit_batch_helpers import MemoryAnchorSink, activate_and_seal
from tests.audit_explorer_helpers import space

pytestmark = pytest.mark.django_db
State = AuditVerificationRunEvent.State


def _row(makerspace, action="audit.page"):
    return audit.record(None, action, makerspace=makerspace, target=makerspace)


def _key(makerspace, rows):
    return SimpleNamespace(
        makerspace_id=makerspace.pk,
        activation_payload={"genesis_rows": [genesis_entry(row) for row in rows]},
    )


def test_oversized_manifest_stops_before_a_database_row_query():
    makerspace = space("genesis-manifest-cap")
    key = _key(makerspace, [_row(makerspace), _row(makerspace)])
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(GenesisMembershipLimitExceeded):
            _verify_genesis_membership(key, row_limit=1)
    assert len(queries) == 0


def test_oversized_legacy_row_set_is_sql_limited_before_hashing(monkeypatch, settings):
    makerspace = space("genesis-legacy-cap")
    settings.AUDIT_MAC_MASTER_KEY = ""
    rows = [_row(makerspace), _row(makerspace)]
    key = _key(makerspace, rows)
    _row(makerspace)  # un-MAC'd history added outside the manifest
    hashed = []
    monkeypatch.setattr("apps.audit.integrity_rows.genesis_entry", lambda row: hashed.append(row.pk))
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(GenesisMembershipLimitExceeded):
            _verify_genesis_membership(key, row_limit=2)
    assert len(queries) == 1
    assert "LIMIT 3" in queries[0]["sql"]
    assert hashed == []


def test_exact_limit_ignores_later_mac_history_and_other_tenants():
    makerspace, other = space("genesis-exact"), space("genesis-other")
    rows = [_row(makerspace), _row(makerspace)]
    key = _key(makerspace, rows)
    for _ in range(4):
        _row(makerspace)
        _row(other)
    assert _verify_genesis_membership(key, row_limit=2) is None


def test_undeclared_unmac_row_remains_invalid_below_limit(settings):
    makerspace = space("genesis-undeclared")
    key = _key(makerspace, [_row(makerspace)])
    settings.AUDIT_MAC_MASTER_KEY = ""
    undeclared = _row(makerspace)
    failure = _verify_genesis_membership(key, row_limit=2)
    assert failure.failure_class == AuditFailureClass.CUTOVER_MEMBERSHIP
    assert failure.audit_log_id == undeclared.pk


@pytest.mark.parametrize("tamper", ["changed", "missing"])
def test_bounded_check_still_detects_changed_or_missing_genesis_rows(tamper):
    makerspace = space(f"genesis-{tamper}")
    row = _row(makerspace)
    key = _key(makerspace, [row])
    entry = key.activation_payload["genesis_rows"][0]
    if tamper == "changed":
        entry["content_sha256"] = "0" * 64
    else:
        entry["audit_log_id"] = row.pk + 1_000_000
    failure = _verify_genesis_membership(key, row_limit=2)
    assert failure.failure_class == AuditFailureClass.CUTOVER_MEMBERSHIP
    assert failure.audit_log_id == entry["audit_log_id"]


def test_anchor_genesis_exhaustion_finishes_incomplete_without_retry(monkeypatch, settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-genesis-bounds"
    makerspace = space("genesis-task-cap")
    for _ in range(3):
        _row(makerspace)
    sink = MemoryAnchorSink()
    activate_and_seal(makerspace.pk, sink)
    _row(makerspace, "audit.later")
    monkeypatch.setattr(runs, "_enqueue", lambda run_id, countdown=0: None)
    run, _ = runs.request_run(None, makerspace.pk, {"action": "audit.later"})
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "http"
    monkeypatch.setattr("apps.audit.integrity_scope.configured_sink", lambda read_budget=None: sink)
    monkeypatch.setattr(runs, "MAX_EXPANDED_LEAVES", 2)
    reads = []
    monkeypatch.setattr(sink, "fetch", lambda identity: reads.append(identity))

    event = execute_attempt(run.pk)
    assert event.state == State.INCOMPLETE
    assert event.failure_code == "verification_bounds_exceeded"
    assert event.anchor_status == "unavailable"
    assert event.row_count == event.mac_valid_count == 1  # local aggregates survive
    assert not run.events.filter(state=State.RETRYING).exists()
    assert reads == []  # manifest bound is checked before signature or sink work
    assert AuditLog.objects.filter(
        makerspace=makerspace, action="audit.verification_finished", meta={"status": "INCOMPLETE"}
    ).exists()


def test_anchor_genesis_at_exact_limit_remains_anchored(monkeypatch, settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-genesis-exact"
    makerspace = space("genesis-task-exact")
    for _ in range(2):
        _row(makerspace)
    sink = MemoryAnchorSink()
    activate_and_seal(makerspace.pk, sink)
    monkeypatch.setattr(runs, "_enqueue", lambda run_id, countdown=0: None)
    run, _ = runs.request_run(None, makerspace.pk, {})
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "http"
    monkeypatch.setattr("apps.audit.integrity_scope.configured_sink", lambda read_budget=None: sink)
    monkeypatch.setattr(runs, "MAX_EXPANDED_LEAVES", 2)
    event = execute_attempt(run.pk)
    assert event.state == State.SUCCEEDED
    assert event.anchor_status == "externally_anchored"
    assert event.externally_anchored_count == event.row_count == 2


def test_post_admission_legacy_growth_terminates_with_the_same_bounds_outcome(monkeypatch, settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-genesis-growth"
    makerspace = space("genesis-task-growth")
    _row(makerspace)
    sink = MemoryAnchorSink()
    activate_and_seal(makerspace.pk, sink)
    _row(makerspace, "audit.later")
    monkeypatch.setattr(runs, "_enqueue", lambda run_id, countdown=0: None)
    run, _ = runs.request_run(None, makerspace.pk, {"action": "audit.later"})
    master_key = settings.AUDIT_MAC_MASTER_KEY
    settings.AUDIT_MAC_MASTER_KEY = ""
    for _ in range(3):
        _row(makerspace, "audit.legacy")
    settings.AUDIT_MAC_MASTER_KEY = master_key
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "http"
    monkeypatch.setattr("apps.audit.integrity_scope.configured_sink", lambda read_budget=None: sink)
    monkeypatch.setattr(runs, "MAX_EXPANDED_LEAVES", 2)
    event = execute_attempt(run.pk)
    assert event.state == State.INCOMPLETE
    assert event.failure_code == "verification_bounds_exceeded"
    assert event.anchor_status == "unavailable"
    assert event.row_count == event.mac_valid_count == 1
    assert not run.events.filter(state=State.RETRYING).exists()
