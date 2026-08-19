"""Tampering signals once row coordinates are signed and externally anchored."""

import pytest
from django.db import connection

from apps.audit.batch_format import batch_payload, canonical_payload_bytes
from apps.audit.batch_verification import AuditFailureClass
from apps.audit.batches import batch_envelope, seal_scope
from apps.audit.integrity import verify_audit_integrity
from apps.audit.services import record
from apps.audit.verification import AuditMacStatus, classify_audit_row
from apps.ed25519 import Ed25519Error, verify_bytes
from tests.audit_batch_helpers import MemoryAnchorSink, activate_and_seal
from tests.audit_mac_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deployment_identity(settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-deployment-aud2"


def _raw_update(sql, params):
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        try:
            cursor.execute(sql, params)
        finally:
            cursor.execute("SET LOCAL session_replication_role = 'origin'")


def test_editing_a_batched_row_is_detected():
    actor = make_user("audit-batch-edit")
    space = make_space("audit-batch-edit")
    row = record(actor, "audit.before", makerspace=space)
    activate_and_seal(space.pk, MemoryAnchorSink())

    _raw_update(
        "UPDATE audit_auditlog SET action = %s WHERE id = %s",
        ["audit.after", row.pk],
    )
    row.refresh_from_db()

    assert classify_audit_row(row) is AuditMacStatus.MISMATCH


def test_clearing_batched_row_mac_is_tampering_not_history():
    actor = make_user("audit-batch-clear")
    space = make_space("audit-batch-clear")
    row = record(actor, "audit.clear", makerspace=space)
    activate_and_seal(space.pk, MemoryAnchorSink())

    _raw_update(
        "UPDATE audit_auditlog SET row_mac = NULL WHERE id = %s",
        [row.pk],
    )
    row.refresh_from_db()

    assert classify_audit_row(row) is AuditMacStatus.MISMATCH


def test_rewriting_batched_row_id_is_detected_by_missing_signed_membership():
    actor = make_user("audit-batch-id")
    space = make_space("audit-batch-id")
    sink = MemoryAnchorSink()
    activate_and_seal(None, sink)
    key, _empty = activate_and_seal(space.pk, sink)
    row = record(actor, "audit.id", makerspace=space)
    batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(batch))
    old_id = row.pk
    new_id = old_id + 1_000_000

    _raw_update(
        "UPDATE audit_auditlog SET id = %s WHERE id = %s",
        [new_id, old_id],
    )
    failure = verify_audit_integrity(sink=sink)

    assert failure.failure_class is AuditFailureClass.LEAF_MEMBERSHIP
    assert failure.batch_seq == 1


def test_prev_batch_root_rewrite_reports_chain_continuity_first():
    actor = make_user("audit-batch-chain")
    space = make_space("audit-batch-chain")
    record(actor, "audit.chain.1", makerspace=space)
    sink = MemoryAnchorSink()
    activate_and_seal(None, sink)
    key, _first = activate_and_seal(space.pk, sink)
    record(actor, "audit.chain.2", makerspace=space)
    second = seal_scope(space.pk, key)
    sink.publish(batch_envelope(second))

    _raw_update(
        "UPDATE audit_auditbatch SET prev_batch_root = %s WHERE id = %s",
        [b"x" * 32, second.pk],
    )
    failure = verify_audit_integrity(sink=sink)

    assert failure.failure_class is AuditFailureClass.CHAIN_CONTINUITY
    assert failure.batch_seq == 2


def test_signed_root_cannot_be_replayed_into_another_scope():
    actor = make_user("audit-batch-replay")
    first_space = make_space("audit-batch-replay-a")
    second_space = make_space("audit-batch-replay-b")
    row = record(actor, "audit.replay", makerspace=first_space)
    key, batch = activate_and_seal(first_space.pk, MemoryAnchorSink())
    rows = [row]
    replay_payload = batch_payload(
        deployment_id="test-deployment-aud2",
        makerspace_id=second_space.pk,
        batch_seq=batch.batch_seq,
        rows=rows,
        root=batch.merkle_root,
        prev_root=None,
        created_at=batch.created_at,
        signer_fingerprint=key.fingerprint,
    )

    with pytest.raises(Ed25519Error):
        verify_bytes(
            canonical_payload_bytes(replay_payload),
            bytes(batch.signature),
            bytes(key.public_key),
        )
