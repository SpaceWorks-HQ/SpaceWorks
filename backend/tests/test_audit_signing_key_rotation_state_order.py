"""Database-enforced append-only rotation state ordering."""

import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit.batches import activate_scope, batch_envelope, seal_scope
from apps.audit.models import AuditSigningKeyRotationEvent
from apps.audit.rotations import prepare_rotation, scope_head
from apps.audit.services import record
from tests.audit_batch_helpers import MemoryAnchorSink
from tests.audit_mac_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deployment_identity(settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-deployment-rotation-order"


def _prepared(name):
    actor = make_user(f"{name}-actor")
    space = make_space(name)
    sink = MemoryAnchorSink()
    key = activate_scope(space.pk, sink)
    record(actor, "audit.rotation.order-head", makerspace=space)
    batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(batch))
    head_seq, head_root = scope_head(space.pk)
    rotation, _created = prepare_rotation(
        space.pk,
        actor=actor,
        expected_fingerprint=key.fingerprint,
        expected_head_seq=head_seq,
        expected_head_root=head_root,
    )
    return rotation


def _put_in_state(rotation, state):
    states = AuditSigningKeyRotationEvent.State
    if state is None:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
            rotation.events.all().delete()
    elif state == states.PUBLISHED:
        rotation.events.create(state=states.PUBLISHED)
    elif state == states.FINALIZED:
        rotation.events.create(state=states.PUBLISHED)
        rotation.events.create(state=states.FINALIZED)
    elif state == states.ABORTED:
        rotation.events.create(state=states.ABORTED)


@pytest.mark.parametrize(
    ("prior_state", "attempted_state"),
    [
        (None, "PUBLISHED"),
        (None, "FINALIZED"),
        (None, "ABORTED"),
        ("PREPARED", "FINALIZED"),
        ("PUBLISHED", "ABORTED"),
        ("FINALIZED", "ABORTED"),
        ("ABORTED", "PUBLISHED"),
        ("ABORTED", "FINALIZED"),
    ],
)
def test_database_rejects_each_out_of_order_state_insert(prior_state, attempted_state):
    suffix = f"{prior_state or 'none'}-{attempted_state}".lower()
    rotation = _prepared(f"audit-rotation-order-{suffix}")
    _put_in_state(rotation, prior_state)

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            rotation.events.create(state=attempted_state)


def test_rotation_row_rejects_update_and_unauthorized_delete():
    rotation = _prepared("audit-rotation-immutable")
    _assert_trigger_rejects(
        "audit_auditsigningkeyrotation", "old_fingerprint", rotation.pk
    )


def test_rotation_event_rejects_update_and_unauthorized_delete():
    rotation = _prepared("audit-rotation-event-immutable")
    event = AuditSigningKeyRotationEvent.objects.get(rotation=rotation)
    _assert_trigger_rejects(
        "audit_auditsigningkeyrotationevent", "state", event.pk
    )


def _assert_trigger_rejects(table, column, pk):
    for statement in (
        f"UPDATE {table} SET {column} = {column} WHERE id = %s",
        f"DELETE FROM {table} WHERE id = %s",
    ):
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(statement, [pk])
