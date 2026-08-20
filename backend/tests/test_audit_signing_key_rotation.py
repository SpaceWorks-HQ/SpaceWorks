"""Ed25519 signing-key rotation intervals, gate, protocol, and immutability."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction

from apps.audit.batch_verification import verify_batch_local
from apps.audit.batches import (
    AuditBatchError,
    AuditSigningKeyRotationPending,
    activate_scope,
    batch_envelope,
    seal_scope,
)
from apps.audit.integrity import verify_audit_integrity
from apps.audit.models import (
    AuditLog,
    AuditSigningKey,
    AuditSigningKeyRotationEvent,
)
from apps.audit.rotations import (
    finalize_rotation,
    prepare_rotation,
    publish_rotation,
    scope_head,
    validate_rotation,
)
from apps.audit.services import record
from apps.audit.signing import key_authorizes_sequence
from tests.audit_batch_helpers import MemoryAnchorSink, activate_and_seal
from tests.audit_mac_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deployment_identity(settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-deployment-rotation"


def _prepared(space, sink, actor):
    old_key = activate_scope(space.pk, sink)
    record(actor, "audit.rotation.old", makerspace=space)
    old_batch = seal_scope(space.pk, old_key)
    sink.publish(batch_envelope(old_batch))
    head_seq, head_root = scope_head(space.pk)
    rotation, created = prepare_rotation(
        space.pk,
        expected_fingerprint=old_key.fingerprint,
        expected_head_seq=head_seq,
        expected_head_root=head_root,
    )
    assert created
    return old_key, old_batch, rotation


def _finalize(rotation, sink):
    publish_rotation(rotation, sink)
    return finalize_rotation(rotation, sink)


def test_generations_coexist_transition_is_dual_signed_and_new_key_activates():
    actor = make_user("audit-rotation-generations")
    space = make_space("audit-rotation-generations")
    sink = MemoryAnchorSink()
    old_key, old_batch, rotation = _prepared(space, sink, actor)

    envelope = validate_rotation(rotation)
    new_key = _finalize(rotation, sink)
    old_key.refresh_from_db()

    assert envelope["old_signature"] and envelope["new_signature"]
    assert list(
        AuditSigningKey.objects.filter(makerspace=space)
        .order_by("version").values_list("version", flat=True)
    ) == [1, 2]
    assert old_key.valid_to_seq == old_batch.batch_seq
    assert old_key.wrapped_private_key is None
    assert not old_key.is_active
    assert new_key.is_active and new_key.valid_from_seq == old_batch.batch_seq + 1


def test_old_and_new_batches_verify_once_across_the_rotation_chain():
    actor = make_user("audit-rotation-integrity")
    space = make_space("audit-rotation-integrity")
    sink = MemoryAnchorSink()
    activate_and_seal(None, sink)
    _old_key, old_batch, rotation = _prepared(space, sink, actor)
    new_key = _finalize(rotation, sink)
    record(actor, "audit.rotation.new", makerspace=space)
    new_batch = seal_scope(space.pk, new_key)
    sink.publish(batch_envelope(new_batch))

    assert verify_batch_local(old_batch) is None
    assert verify_batch_local(new_batch) is None
    assert verify_audit_integrity(sink=sink) is None


def test_retired_key_is_explicitly_rejected_for_n_plus_one():
    actor = make_user("audit-rotation-retired")
    space = make_space("audit-rotation-retired")
    sink = MemoryAnchorSink()
    old_key, old_batch, rotation = _prepared(space, sink, actor)
    _finalize(rotation, sink)
    old_key.refresh_from_db()
    record(actor, "audit.rotation.after-retirement", makerspace=space)

    assert not key_authorizes_sequence(old_key, old_batch.batch_seq + 1)
    with pytest.raises(AuditBatchError, match="active"):
        seal_scope(space.pk, old_key)


def test_anchor_publish_failure_leaves_resumable_gate_and_old_key_active():
    actor = make_user("audit-rotation-resume")
    space = make_space("audit-rotation-resume")
    sink = MemoryAnchorSink()
    old_key, _batch, rotation = _prepared(space, sink, actor)
    sink.fail_publish = True

    with pytest.raises(RuntimeError, match="anchor unavailable"):
        publish_rotation(rotation, sink)
    old_key.refresh_from_db()
    assert old_key.is_active and old_key.pending_rotation_id == rotation.pk
    assert list(rotation.events.values_list("state", flat=True)) == ["PREPARED"]

    sink.fail_publish = False
    new_key = _finalize(rotation, sink)
    assert new_key.is_active
    assert list(rotation.events.values_list("state", flat=True)) == [
        "PREPARED", "PUBLISHED", "FINALIZED",
    ]


def test_pending_rotation_refuses_sealing_but_audit_row_mac_writes_continue():
    actor = make_user("audit-rotation-gate")
    space = make_space("audit-rotation-gate")
    sink = MemoryAnchorSink()
    old_key, _batch, _rotation = _prepared(space, sink, actor)

    row = record(actor, "audit.rotation.during-gate", makerspace=space)
    assert row.row_mac is not None
    with pytest.raises(AuditSigningKeyRotationPending):
        seal_scope(space.pk, old_key)


def test_command_refuses_actor_who_is_not_an_active_superuser():
    actor = make_user("audit-rotation-non-superuser")
    with pytest.raises(CommandError, match="active superuser"):
        call_command(
            "rotate_audit_signing_key",
            "--global",
            "--actor-user-id", str(actor.pk),
            "--dry-run",
            stdout=StringIO(),
        )


def test_command_emits_started_and_completed_with_bound_head(monkeypatch):
    actor = make_user("audit-rotation-command")
    actor.is_superuser = True
    actor.save(update_fields=["is_superuser"])
    space = make_space("audit-rotation-command")
    sink = MemoryAnchorSink()
    key = activate_scope(space.pk, sink)
    record(actor, "audit.rotation.command-head", makerspace=space)
    batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(batch))
    head_seq, head_root = scope_head(space.pk)
    monkeypatch.setattr(
        "apps.audit.management.commands.rotate_audit_signing_key.configured_sink",
        lambda: sink,
    )

    call_command(
        "rotate_audit_signing_key",
        "--makerspace-id", str(space.pk),
        "--actor-user-id", str(actor.pk),
        "--execute",
        "--expected-current-fingerprint", key.fingerprint,
        "--expected-head-seq", str(head_seq),
        "--expected-head-root", head_root.hex(),
        stdout=StringIO(),
    )

    events = AuditLog.objects.filter(
        action__in={
            "audit.signing_key_rotation_started",
            "audit.signing_key_rotation_completed",
        }
    ).order_by("pk")
    assert [event.action for event in events] == [
        "audit.signing_key_rotation_started",
        "audit.signing_key_rotation_completed",
    ]
    assert all(event.meta["last_old_batch_seq"] == head_seq for event in events)
    assert events[0].meta["rotation_id"] == events[1].meta["rotation_id"]


def test_rotation_row_rejects_update_and_unauthorized_delete():
    actor = make_user("audit-rotation-immutable")
    space = make_space("audit-rotation-immutable")
    _old, _batch, rotation = _prepared(space, MemoryAnchorSink(), actor)
    _assert_trigger_rejects(
        "audit_auditsigningkeyrotation", "old_fingerprint", rotation.pk
    )


def test_rotation_event_rejects_update_and_unauthorized_delete():
    actor = make_user("audit-rotation-event-immutable")
    space = make_space("audit-rotation-event-immutable")
    _old, _batch, rotation = _prepared(space, MemoryAnchorSink(), actor)
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
