"""Crash recovery and operator controls for audit signing-key rotation."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.anchors import AnchorConflict
from apps.audit.batches import activate_scope, batch_envelope, seal_scope
from apps.audit.models import (
    AuditLog,
    AuditSigningKey,
    AuditSigningKeyRotation,
)
from apps.audit.rotations import (
    AuditSigningKeyRotationError,
    abort_rotation,
    finalize_rotation,
    prepare_rotation,
    publish_rotation,
    scope_head,
    validate_rotation,
)
from apps.audit.services import record
from tests.audit_batch_helpers import MemoryAnchorSink
from tests.audit_mac_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deployment_identity(settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-deployment-rotation-recovery"


def _superuser(username):
    actor = make_user(username)
    actor.is_superuser = True
    actor.save(update_fields=["is_superuser"])
    return actor


def _prepare_head(space, sink, actor):
    key = activate_scope(space.pk, sink)
    record(actor, "audit.rotation.recovery-head", makerspace=space)
    batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(batch))
    head_seq, head_root = scope_head(space.pk)
    rotation, created = prepare_rotation(
        space.pk,
        actor=actor,
        expected_fingerprint=key.fingerprint,
        expected_head_seq=head_seq,
        expected_head_root=head_root,
    )
    assert created
    return key, rotation


def _execute_args(space, actor, key):
    head_seq, head_root = scope_head(space.pk)
    return (
        "rotate_audit_signing_key",
        "--makerspace-id", str(space.pk),
        "--actor-user-id", str(actor.pk),
        "--execute",
        "--expected-current-fingerprint", key.fingerprint,
        "--expected-head-seq", str(head_seq),
        "--expected-head-root", head_root.hex(),
    )


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
    actor = _superuser("audit-rotation-command")
    space = make_space("audit-rotation-command")
    sink = MemoryAnchorSink()
    key = activate_scope(space.pk, sink)
    record(actor, "audit.rotation.command-head", makerspace=space)
    batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(batch))
    head_seq, _head_root = scope_head(space.pk)
    monkeypatch.setattr(
        "apps.audit.management.commands.rotate_audit_signing_key.configured_sink",
        lambda: sink,
    )

    call_command(*_execute_args(space, actor, key), stdout=StringIO())

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


def test_prepare_audit_failure_rolls_back_and_retry_records_started_once(monkeypatch):
    actor = _superuser("audit-rotation-prepare-crash")
    space = make_space("audit-rotation-prepare-crash")
    sink = MemoryAnchorSink()
    key = activate_scope(space.pk, sink)
    record(actor, "audit.rotation.prepare-crash-head", makerspace=space)
    batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(batch))
    head_seq, head_root = scope_head(space.pk)
    from apps.audit import rotation_lifecycle

    real_record = rotation_lifecycle.audit.record
    crashed = False

    def crash_once(*args, **kwargs):
        nonlocal crashed
        if not crashed and args[1] == "audit.signing_key_rotation_started":
            crashed = True
            raise RuntimeError("simulated crash before audit write")
        return real_record(*args, **kwargs)

    monkeypatch.setattr(rotation_lifecycle.audit, "record", crash_once)
    kwargs = {
        "actor": actor,
        "expected_fingerprint": key.fingerprint,
        "expected_head_seq": head_seq,
        "expected_head_root": head_root,
    }
    with pytest.raises(RuntimeError, match="simulated crash"):
        prepare_rotation(space.pk, **kwargs)

    key.refresh_from_db()
    assert key.pending_rotation_id is None
    assert AuditSigningKey.objects.filter(makerspace=space).count() == 1
    rotation, created = prepare_rotation(space.pk, **kwargs)
    assert created and rotation.events.get().state == "PREPARED"
    assert AuditLog.objects.filter(
        action="audit.signing_key_rotation_started",
        meta__rotation_id=str(rotation.pk),
    ).count() == 1


def test_finalize_audit_failure_rolls_back_and_retry_records_completion_once(monkeypatch):
    actor = _superuser("audit-rotation-finalize-crash")
    space = make_space("audit-rotation-finalize-crash")
    sink = MemoryAnchorSink()
    old_key, rotation = _prepare_head(space, sink, actor)
    publish_rotation(rotation, sink)
    from apps.audit import rotation_lifecycle

    real_record = rotation_lifecycle.audit.record
    crashed = False

    def crash_once(*args, **kwargs):
        nonlocal crashed
        if not crashed and args[1] == "audit.signing_key_rotation_completed":
            crashed = True
            raise RuntimeError("simulated completion audit crash")
        return real_record(*args, **kwargs)

    monkeypatch.setattr(rotation_lifecycle.audit, "record", crash_once)
    with pytest.raises(RuntimeError, match="completion audit crash"):
        finalize_rotation(rotation, sink, actor=actor)
    old_key.refresh_from_db()
    assert old_key.is_active and old_key.pending_rotation_id == rotation.pk
    assert list(rotation.events.values_list("state", flat=True)) == [
        "PREPARED", "PUBLISHED",
    ]

    new_key = finalize_rotation(rotation, sink, actor=actor)
    assert new_key.is_active
    assert AuditLog.objects.filter(
        action="audit.signing_key_rotation_completed",
        meta__rotation_id=str(rotation.pk),
    ).count() == 1


def test_prepublication_anchor_conflict_aborts_and_restores_sealing(monkeypatch):
    actor = _superuser("audit-rotation-conflict")
    space = make_space("audit-rotation-conflict")
    sink = MemoryAnchorSink()
    key = activate_scope(space.pk, sink)
    record(actor, "audit.rotation.conflict-head", makerspace=space)
    batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(batch))
    monkeypatch.setattr(
        "apps.audit.management.commands.rotate_audit_signing_key.configured_sink",
        lambda: sink,
    )
    monkeypatch.setattr(
        sink,
        "publish_rotation",
        lambda _envelope: (_ for _ in ()).throw(AnchorConflict("anchor conflict")),
    )

    with pytest.raises(CommandError, match="anchor conflict"):
        call_command(*_execute_args(space, actor, key), stdout=StringIO())

    rotation = AuditSigningKeyRotation.objects.get(makerspace=space)
    key.refresh_from_db()
    assert list(rotation.events.values_list("state", flat=True)) == [
        "PREPARED", "ABORTED",
    ]
    assert key.is_active and key.valid_to_seq is None
    assert key.wrapped_private_key is not None and key.pending_rotation_id is None
    assert AuditLog.objects.filter(
        action="audit.signing_key_rotation_aborted",
        meta__rotation_id=str(rotation.pk),
    ).count() == 1
    record(actor, "audit.rotation.after-abort", makerspace=space)
    assert seal_scope(space.pk, key) is not None


def test_abort_refuses_a_published_rotation():
    actor = _superuser("audit-rotation-published-abort")
    space = make_space("audit-rotation-published-abort")
    sink = MemoryAnchorSink()
    old_key, rotation = _prepare_head(space, sink, actor)
    # Simulate a process dying after the external write but before PUBLISHED commits.
    sink.publish_rotation(validate_rotation(rotation))

    with pytest.raises(AuditSigningKeyRotationError, match="externally published"):
        abort_rotation(rotation, sink, actor=actor)
    old_key.refresh_from_db()
    assert old_key.pending_rotation_id == rotation.pk
    assert list(rotation.events.values_list("state", flat=True)) == ["PREPARED"]


def test_operator_abort_releases_a_pending_scope(monkeypatch):
    actor = _superuser("audit-rotation-operator-abort")
    space = make_space("audit-rotation-operator-abort")
    sink = MemoryAnchorSink()
    old_key, rotation = _prepare_head(space, sink, actor)
    monkeypatch.setattr(
        "apps.audit.management.commands.rotate_audit_signing_key.configured_sink",
        lambda: sink,
    )

    call_command(
        "rotate_audit_signing_key",
        "--makerspace-id", str(space.pk),
        "--actor-user-id", str(actor.pk),
        "--abort-pending",
        stdout=StringIO(),
    )

    old_key.refresh_from_db()
    assert old_key.pending_rotation_id is None and old_key.is_active
    assert list(rotation.events.values_list("state", flat=True)) == [
        "PREPARED", "ABORTED",
    ]
    record(actor, "audit.rotation.operator-aborted", makerspace=space)
    assert seal_scope(space.pk, old_key) is not None
