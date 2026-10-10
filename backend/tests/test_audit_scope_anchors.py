"""The scoped anchor phase never falls back to one membership query per batch."""

from copy import deepcopy

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit import services as audit
from apps.audit import verification_runs as runs
from apps.audit.anchors import AnchorReadBudget
from apps.audit.batch_verification import AuditFailureClass
from apps.audit.batches import batch_envelope
from apps.audit.integrity_scope import anchor_phase, local_phase
from apps.audit.integrity_scope_anchors import verify_scope_batch_anchor
from apps.audit.models import AuditLog
from tests.audit_batch_helpers import MemoryAnchorSink, activate_and_seal
from tests.audit_explorer_helpers import space

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _identity(settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-scope-anchors"


def _batch(makerspace, sink, action="audit.page"):
    for _ in range(2):
        audit.record(None, action, makerspace=makerspace, target=makerspace)
    return activate_and_seal(makerspace.pk, sink)


def _configure(sink, settings, monkeypatch):
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "http"
    monkeypatch.setattr("apps.audit.integrity_scope.configured_sink", lambda read_budget=None: sink)
    # The scoped verifier must not rebuild ANY envelope via per-batch relation queries.
    def refuse(_batch):
        pytest.fail("Scoped verification fell back to rebuilding a batch envelope.")
    monkeypatch.setattr("apps.audit.integrity_batches.batch_envelope", refuse)


def _verify(makerspace, rows):
    result = local_phase(makerspace.pk, rows)
    return anchor_phase(makerspace.pk, result, read_budget=AnchorReadBudget(runs.MAX_ANCHOR_READS),
                        genesis_row_limit=runs.MAX_EXPANDED_LEAVES)


def test_database_queries_do_not_grow_per_distinct_anchored_batch(settings, monkeypatch):
    one, many = space("anchor-q-one"), space("anchor-q-many")
    sink = MemoryAnchorSink()
    _batch(one, sink)
    for _ in range(4):
        _batch(many, sink)
    _configure(sink, settings, monkeypatch)

    def measure(makerspace):
        rows = list(AuditLog.objects.filter(makerspace=makerspace).order_by("pk"))
        with CaptureQueriesContext(connection) as queries:
            result = _verify(makerspace, rows)
        assert result.anchor_status == "externally_anchored"
        assert result.counts["externally_anchored_count"] == len(rows)
        return len(queries), result

    one_queries, one_result = measure(one)
    many_queries, many_result = measure(many)
    assert len(many_result.batch_results) == 4
    assert len(one_result.batch_results) == 1
    assert many_queries == one_queries


def test_unselected_batches_are_anchored_without_loading_local_leaves(settings, monkeypatch):
    makerspace = space("anchor-unselected")
    sink = MemoryAnchorSink()
    _batch(makerspace, sink, "audit.first")
    _batch(makerspace, sink, "audit.second")
    _configure(sink, settings, monkeypatch)
    rows = list(AuditLog.objects.filter(makerspace=makerspace, action="audit.second"))
    result = _verify(makerspace, rows)
    assert len(result.batch_results) == 1
    assert result.anchor_status == "externally_anchored"
    assert result.counts["local_batch_verified_count"] == result.counts["externally_anchored_count"] == 2


@pytest.mark.parametrize("tamper", ["root", "signature", "key", "leaf", "leaf_count", "extra"])
def test_fetched_envelope_must_match_local_signed_state(tamper):
    makerspace = space(f"anchor-tamper-{tamper}")
    key, batch = _batch(makerspace, MemoryAnchorSink())
    envelope = deepcopy(batch_envelope(batch))
    if tamper == "root":
        envelope["payload"]["merkle_root"] = "0" * 64
    elif tamper == "signature":
        envelope["signature"] = "0" * 128
    elif tamper == "key":
        envelope["public_key"] = "wrong"
    elif tamper == "leaf":
        envelope["payload"]["leaves"][0]["audit_log_id"] += 1_000_000
    elif tamper == "leaf_count":
        envelope["payload"]["leaves"].pop()
    else:
        envelope["payload"]["extra"] = "unexpected"
    failure = verify_scope_batch_anchor(batch, key, envelope)
    assert failure.failure_class == AuditFailureClass.ANCHOR_CONFLICT
    assert failure.batch_seq == batch.batch_seq


def test_a_valid_fetched_envelope_requires_no_database_query():
    makerspace = space("anchor-no-query")
    key, batch = _batch(makerspace, MemoryAnchorSink())
    envelope = batch_envelope(batch)
    with CaptureQueriesContext(connection) as queries:
        assert verify_scope_batch_anchor(batch, key, envelope) is None
    assert len(queries) == 0


def test_rotated_batches_verify_the_protocol_two_envelope(settings, monkeypatch):
    from apps.audit.batches import seal_scope
    from apps.audit.rotations import finalize_rotation, prepare_rotation, publish_rotation, scope_head

    makerspace = space("anchor-rotated-batch")
    sink = MemoryAnchorSink()
    old_key, _ = _batch(makerspace, sink)
    sequence, root = scope_head(makerspace.pk)
    rotation, _ = prepare_rotation(
        makerspace.pk, actor=None, expected_fingerprint=old_key.fingerprint,
        expected_head_seq=sequence, expected_head_root=root,
    )
    publish_rotation(rotation, sink)
    new_key = finalize_rotation(rotation, sink, actor=None)
    audit.record(None, "audit.after_rotation", makerspace=makerspace, target=makerspace)
    batch = seal_scope(makerspace.pk, new_key)
    envelope = batch_envelope(batch)
    assert envelope["payload"]["anchor_protocol_version"] == 2
    sink.publish(envelope)
    _configure(sink, settings, monkeypatch)
    result = _verify(makerspace, list(AuditLog.objects.filter(makerspace=makerspace)))
    assert result.anchor_status == "externally_anchored"
