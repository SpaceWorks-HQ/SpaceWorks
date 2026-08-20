"""Crash recovery invariants for audit signing-key rotation."""

import pytest

from apps.audit.batches import activate_scope, batch_envelope, seal_scope
from apps.audit.integrity_rotations import _verify_rotation_chain
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


def test_abort_refuses_a_published_rotation():
    actor = _superuser("audit-rotation-published-abort")
    space = make_space("audit-rotation-published-abort")
    sink = MemoryAnchorSink()
    old_key, rotation = _prepare_head(space, sink, actor)
    # Simulate a process dying after the external write but before PUBLISHED commits.
    sink.publish_rotation(validate_rotation(rotation))

    with pytest.raises(AuditSigningKeyRotationError, match="must be rolled forward"):
        abort_rotation(rotation, sink, actor=actor)
    old_key.refresh_from_db()
    assert old_key.pending_rotation_id == rotation.pk
    assert list(rotation.events.values_list("state", flat=True)) == ["PREPARED"]


def test_abort_then_second_rotation_succeeds_and_chain_ignores_candidate():
    actor = _superuser("audit-rotation-abort-retry")
    space = make_space("audit-rotation-abort-retry")
    sink = MemoryAnchorSink()
    old_key, aborted = _prepare_head(space, sink, actor)
    abort_rotation(aborted, sink, actor=actor)
    head_seq, head_root = scope_head(space.pk)

    retry, created = prepare_rotation(
        space.pk,
        actor=actor,
        expected_fingerprint=old_key.fingerprint,
        expected_head_seq=head_seq,
        expected_head_root=head_root,
    )
    assert created and retry.old_key_id == old_key.pk
    assert retry.new_version == aborted.new_version + 1
    publish_rotation(retry, sink)
    new_key = finalize_rotation(retry, sink, actor=actor)

    keys = list(
        AuditSigningKey.objects.filter(makerspace=space).order_by("version")
    )
    aborted.new_key.refresh_from_db()
    assert [key.version for key in keys] == [1, 2, 3]
    assert new_key.is_active and _verify_rotation_chain(keys, sink) is None
    assert aborted.new_key.wrapped_private_key is None
    assert AuditSigningKeyRotation.objects.filter(pk=aborted.pk).exists()
    assert list(aborted.events.values_list("state", flat=True)) == [
        "PREPARED", "ABORTED",
    ]


@pytest.mark.parametrize("divergence", ["rotation", "batch"])
def test_abort_refuses_any_diverged_external_scope_head(divergence):
    actor = _superuser(f"audit-rotation-diverged-{divergence}")
    space = make_space(f"audit-rotation-diverged-{divergence}")
    sink = MemoryAnchorSink()
    old_key, rotation = _prepare_head(space, sink, actor)
    payload = validate_rotation(rotation)["payload"]
    identity = (payload["deployment_id"], payload["scope"])
    if divergence == "rotation":
        sink.rotations[
            (*identity, old_key.fingerprint, "f" * 64, rotation.last_old_batch_seq)
        ] = {}
    else:
        sink.anchors[
            (*identity, old_key.fingerprint, rotation.last_old_batch_seq + 1)
        ] = {"payload": {"merkle_root": "ab" * 32}}

    old_key.refresh_from_db()
    with pytest.raises(AuditSigningKeyRotationError, match="scope head diverged"):
        abort_rotation(rotation, sink, actor=actor)
    old_key.refresh_from_db()
    assert old_key.pending_rotation_id == rotation.pk and old_key.is_active
    assert list(rotation.events.values_list("state", flat=True)) == ["PREPARED"]
