"""Ed25519 signing-key rotation intervals, gate, and protocol."""

import pytest

from apps.audit.batch_verification import verify_batch_local
from apps.audit.batches import (
    AuditBatchError,
    AuditSigningKeyRotationPending,
    activate_scope,
    batch_envelope,
    seal_scope,
)
from apps.audit.integrity import verify_audit_integrity
from apps.audit.models import AuditSigningKey
from apps.audit.rotations import (
    AuditSigningKeyRotationError,
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
        actor=actor,
        expected_fingerprint=old_key.fingerprint,
        expected_head_seq=head_seq,
        expected_head_root=head_root,
    )
    assert created
    return old_key, old_batch, rotation


def _finalize(rotation, sink, actor):
    publish_rotation(rotation, sink)
    return finalize_rotation(rotation, sink, actor=actor)


def test_generations_coexist_transition_is_dual_signed_and_new_key_activates():
    actor = make_user("audit-rotation-generations")
    space = make_space("audit-rotation-generations")
    sink = MemoryAnchorSink()
    old_key, old_batch, rotation = _prepared(space, sink, actor)

    envelope = validate_rotation(rotation)
    new_key = _finalize(rotation, sink, actor)
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
    new_key = _finalize(rotation, sink, actor)
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
    _finalize(rotation, sink, actor)
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
    new_key = _finalize(rotation, sink, actor)
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


def test_second_rotation_at_same_batch_head_is_rejected_before_claim():
    actor = make_user("audit-rotation-same-head")
    space = make_space("audit-rotation-same-head")
    sink = MemoryAnchorSink()
    _old_key, batch, first = _prepared(space, sink, actor)
    second_key = _finalize(first, sink, actor)
    head_seq, head_root = scope_head(space.pk)
    with pytest.raises(AuditSigningKeyRotationError, match="has not sealed"):
        prepare_rotation(
            space.pk,
            actor=actor,
            expected_fingerprint=second_key.fingerprint,
            expected_head_seq=head_seq,
            expected_head_root=head_root,
        )

    second_key.refresh_from_db()
    assert second_key.pending_rotation_id is None
    assert AuditSigningKey.objects.filter(makerspace=space).count() == 2
    assert first.last_old_batch_seq == batch.batch_seq
    record(actor, "audit.rotation.after-rejected-second", makerspace=space)
    sealed = seal_scope(space.pk, second_key)
    assert sealed is not None
    sink.publish(batch_envelope(sealed))
