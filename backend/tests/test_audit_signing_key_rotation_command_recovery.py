"""Operator-command recovery coverage for audit signing-key rotation."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.anchors import AnchorConflict
from apps.audit.batches import activate_scope, batch_envelope, seal_scope
from apps.audit.models import AuditLog, AuditSigningKeyRotation
from apps.audit.rotations import prepare_rotation, scope_head
from apps.audit.services import record
from tests.audit_batch_helpers import MemoryAnchorSink
from tests.audit_mac_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deployment_identity(settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-deployment-rotation-command"


def _superuser(username):
    actor = make_user(username)
    actor.is_superuser = True
    actor.save(update_fields=["is_superuser"])
    return actor


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


def _anchored_head(space, sink, actor):
    key = activate_scope(space.pk, sink)
    record(actor, "audit.rotation.command-head", makerspace=space)
    batch = seal_scope(space.pk, key)
    sink.publish(batch_envelope(batch))
    return key


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
    key = _anchored_head(space, sink, actor)
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


def test_prepublication_anchor_conflict_aborts_and_restores_sealing(monkeypatch):
    actor = _superuser("audit-rotation-conflict")
    space = make_space("audit-rotation-conflict")
    sink = MemoryAnchorSink()
    key = _anchored_head(space, sink, actor)
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
    assert key.is_active and key.pending_rotation_id is None
    assert AuditLog.objects.filter(
        action="audit.signing_key_rotation_aborted",
        meta__rotation_id=str(rotation.pk),
    ).count() == 1
    record(actor, "audit.rotation.after-abort", makerspace=space)
    assert seal_scope(space.pk, key) is not None


def test_operator_abort_releases_a_pending_scope(monkeypatch):
    actor = _superuser("audit-rotation-operator-abort")
    space = make_space("audit-rotation-operator-abort")
    sink = MemoryAnchorSink()
    key = _anchored_head(space, sink, actor)
    head_seq, head_root = scope_head(space.pk)

    rotation, _created = prepare_rotation(
        space.pk,
        actor=actor,
        expected_fingerprint=key.fingerprint,
        expected_head_seq=head_seq,
        expected_head_root=head_root,
    )
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

    key.refresh_from_db()
    assert key.pending_rotation_id is None and key.is_active
    assert list(rotation.events.values_list("state", flat=True)) == [
        "PREPARED", "ABORTED",
    ]
