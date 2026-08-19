"""Set membership, Merkle shape, activation, and scheduler serialization."""

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, connection, transaction

from apps.audit.batch_format import NODE_DOMAIN, hashes_for_rows
from apps.audit.integrity import verify_audit_integrity
from apps.audit.batches import activate_scope, batch_envelope, seal_scope
from apps.audit.canonical import calculate_row_mac
from apps.audit.keys import get_audit_mac_key
from apps.audit.models import AuditBatch, AuditBatchLeaf, AuditLog, AuditSigningKey
from apps.audit.services import record
from tests.audit_batch_helpers import MemoryAnchorSink, activate_and_seal
from tests.audit_mac_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deployment_identity(settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-deployment-aud2"


def _late_row(*, pk, actor, makerspace, action):
    event_uuid = uuid.uuid4()
    created_at = datetime.now(UTC)
    row_mac = calculate_row_mac(
        get_audit_mac_key(makerspace.pk),
        makerspace_id=makerspace.pk,
        event_uuid=event_uuid,
        actor_id=actor.pk,
        action=action,
        target_type="",
        target_id="",
        meta={},
        created_at=created_at,
    )
    row = AuditLog(
        pk=pk,
        actor=actor,
        makerspace=makerspace,
        action=action,
        event_uuid=event_uuid,
        row_mac=row_mac,
        created_at=created_at,
    )
    AuditLog.objects.bulk_create([row])
    return AuditLog.objects.get(pk=pk)


def test_late_lower_id_commit_lands_in_a_later_batch_and_verifies():
    actor = make_user("audit-batch-late")
    space = make_space("audit-batch-late")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT nextval(pg_get_serial_sequence('audit_auditlog', 'id'))"
        )
        reserved_id = cursor.fetchone()[0]
    first = record(actor, "audit.first-visible", makerspace=space)
    sink = MemoryAnchorSink()
    activate_and_seal(None, sink)
    key, first_batch = activate_and_seal(space.pk, sink)

    late = _late_row(
        pk=reserved_id,
        actor=actor,
        makerspace=space,
        action="audit.late-low-id",
    )
    second_batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(second_batch))

    assert late.pk < first.pk
    assert first.batch_leaf.batch == first_batch
    assert late.batch_leaf.batch == second_batch
    assert second_batch.batch_seq == first_batch.batch_seq + 1
    assert verify_audit_integrity(sink=sink) is None


def test_batched_row_cannot_be_rebatched():
    actor = make_user("audit-batch-once")
    space = make_space("audit-batch-once")
    row = record(actor, "audit.once", makerspace=space)
    key, batch = activate_and_seal(space.pk, MemoryAnchorSink())

    assert seal_scope(space.pk, key) is None
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuditBatchLeaf.objects.create(
                batch=batch,
                audit_log=row,
                leaf_position=1,
            )


def test_odd_leaf_is_promoted_instead_of_duplicated():
    actor = make_user("audit-batch-odd")
    space = make_space("audit-batch-odd")
    rows = [record(actor, f"audit.odd.{index}", makerspace=space) for index in range(3)]
    _key, batch = activate_and_seal(space.pk, MemoryAnchorSink())
    first, second, third = hashes_for_rows(rows)
    left = hashlib.sha256(NODE_DOMAIN + first + second).digest()
    promoted_root = hashlib.sha256(NODE_DOMAIN + left + third).digest()

    assert bytes(batch.merkle_root) == promoted_root


def test_double_run_does_not_fork_batch_sequence():
    actor = make_user("audit-batch-double")
    space = make_space("audit-batch-double")
    record(actor, "audit.double", makerspace=space)
    sink = MemoryAnchorSink()
    key = activate_scope(space.pk, sink)

    first = seal_scope(space.pk, key)
    second = seal_scope(space.pk, key)

    assert first.batch_seq == 1
    assert second is None
    assert list(
        AuditBatch.objects.filter(makerspace=space).values_list("batch_seq", flat=True)
    ) == [1]


def test_activation_is_not_declared_when_genesis_anchor_fails():
    space = make_space("audit-batch-genesis-failure")

    with pytest.raises(RuntimeError, match="anchor unavailable"):
        activate_scope(space.pk, MemoryAnchorSink(fail_publish=True))

    assert AuditSigningKey.objects.get(makerspace=space).activated_at is None
