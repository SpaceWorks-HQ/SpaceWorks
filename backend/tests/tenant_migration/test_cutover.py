import uuid
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.makerspaces import lifecycle
from apps.backup.models import MakerspaceArchiveCustodyState
from apps.makerspaces.models import Makerspace
from apps.tenant_migration import cutover
from apps.tenant_migration.models import (
    MigratedOutHandoff,
    MigrationReceipt,
    ReceiptConsumption,
    SourceMigrationGate,
)
from apps.tenant_migration.protocol_errors import TransitionConflictError
from tests.tenant_migration.protocol_helpers import (
    bind_job_state,
    import_job,
    signed_envelope,
    source_pairing,
    superadmin,
    target_pairing,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def encryption_key(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")


def _quiesce_source(source, actor):
    now = timezone.now()
    return SourceMigrationGate.objects.create(
        makerspace=source,
        state=SourceMigrationGate.State.QUIESCED,
        owner_id=uuid.uuid4(),
        fencing_token=1,
        actor=actor,
        heartbeat_at=now,
        lease_expires_at=now + timedelta(hours=1),
        presign_drain_until=now,
        quiesced_at=now,
    )


def test_activation_retry_returns_same_persisted_receipt(monkeypatch):
    actor = superadmin("activate-retry")
    pairing, source, source_private = target_pairing(actor)
    job = import_job(pairing)
    bind_job_state(monkeypatch, job)
    envelope = signed_envelope(
        pairing,
        MigrationReceipt.Operation.SOURCE_CUTOVER,
        source,
        source_private,
    )

    first = cutover.activate_target(
        pairing=pairing, import_job=job, receipt_envelope=envelope, actor=actor
    )
    second = cutover.activate_target(
        pairing=pairing, import_job=job, receipt_envelope=envelope, actor=actor
    )

    job.target_makerspace.refresh_from_db()
    assert first == second == envelope
    assert job.target_makerspace.lifecycle_state == Makerspace.LifecycleState.ACTIVE
    assert MigrationReceipt.objects.filter(pairing=pairing).count() == 1
    assert ReceiptConsumption.objects.count() == 1
    assert MakerspaceArchiveCustodyState.objects.get(
        makerspace=job.target_makerspace
    ).state == MakerspaceArchiveCustodyState.State.NOT_APPLICABLE


def test_aborted_target_cannot_activate(monkeypatch):
    actor = superadmin("abort-first")
    pairing, source, source_private = target_pairing(actor)
    job = import_job(pairing)
    bind_job_state(monkeypatch, job)

    cutover.abort_target(pairing=pairing, import_job=job, actor=actor)
    with pytest.raises(TransitionConflictError, match="IMPORTING"):
        cutover.activate_target(
            pairing=pairing,
            import_job=job,
            receipt_envelope=signed_envelope(
                pairing,
                MigrationReceipt.Operation.SOURCE_CUTOVER,
                source,
                source_private,
            ),
            actor=actor,
        )
    job.target_makerspace.refresh_from_db()
    assert job.target_makerspace.lifecycle_state == Makerspace.LifecycleState.ABORTED


def test_active_target_cannot_abort(monkeypatch):
    actor = superadmin("activate-first")
    pairing, source, source_private = target_pairing(actor)
    job = import_job(pairing)
    bind_job_state(monkeypatch, job)
    cutover.activate_target(
        pairing=pairing,
        import_job=job,
        receipt_envelope=signed_envelope(
            pairing,
            MigrationReceipt.Operation.SOURCE_CUTOVER,
            source,
            source_private,
        ),
        actor=actor,
    )

    with pytest.raises(TransitionConflictError, match="IMPORTING"):
        cutover.abort_target(pairing=pairing, import_job=job, actor=actor)
    job.target_makerspace.refresh_from_db()
    assert job.target_makerspace.lifecycle_state == Makerspace.LifecycleState.ACTIVE


def test_unarchive_refuses_migrated_out_but_allows_ordinary_archive():
    actor = superadmin("unarchive")
    migrated = Makerspace.objects.create(name="Migrated", slug="migrated-out")
    pairing, _target, _target_private = source_pairing(actor, migrated)
    _quiesce_source(migrated, actor)
    cutover.retire_source(pairing=pairing, makerspace=migrated, actor=actor)

    with pytest.raises(ValidationError, match="signed abort receipt"):
        lifecycle.unarchive(migrated, actor)

    ordinary = Makerspace.objects.create(name="Ordinary", slug="ordinary-archive")
    lifecycle.archive(ordinary, actor)
    restored = lifecycle.unarchive(ordinary, actor)
    assert restored.archived_at is None


def test_source_cutover_rolls_back_archive_receipt_and_handoff(monkeypatch):
    actor = superadmin("cutover-rollback")
    source = Makerspace.objects.create(name="Rollback", slug="cutover-rollback")
    pairing, _target, _target_private = source_pairing(actor, source)
    gate = _quiesce_source(source, actor)

    def fail_handoff(**_kwargs):
        raise RuntimeError("injected handoff persistence failure")

    monkeypatch.setattr(MigratedOutHandoff.objects, "create", fail_handoff)
    with pytest.raises(RuntimeError, match="injected"):
        cutover.retire_source(pairing=pairing, makerspace=source, actor=actor)

    source.refresh_from_db()
    gate.refresh_from_db()
    assert source.archived_at is None
    assert gate.state == SourceMigrationGate.State.QUIESCED
    assert not MigratedOutHandoff.objects.filter(pairing=pairing).exists()
    assert not MigrationReceipt.objects.filter(pairing=pairing).exists()


def test_source_cutover_requires_the_quiesced_gate():
    actor = superadmin("cutover-gate")
    source = Makerspace.objects.create(name="Gate", slug="cutover-gate")
    pairing, _target, _target_private = source_pairing(actor, source)

    with pytest.raises(TransitionConflictError, match="quiesced source migration gate"):
        cutover.retire_source(pairing=pairing, makerspace=source, actor=actor)

    source.refresh_from_db()
    assert source.archived_at is None
    assert not MigrationReceipt.objects.filter(pairing=pairing).exists()


def test_reopen_retry_consumes_one_abort_receipt(monkeypatch):
    actor = superadmin("reopen-retry")
    source = Makerspace.objects.create(name="Reopen", slug="reopen-retry")
    pairing, target, target_private = source_pairing(actor, source)
    gate = _quiesce_source(source, actor)
    cutover.retire_source(pairing=pairing, makerspace=source, actor=actor)
    gate.refresh_from_db()
    assert gate.state == SourceMigrationGate.State.MIGRATED_OUT
    abort_envelope = signed_envelope(
        pairing,
        MigrationReceipt.Operation.TARGET_ABORT,
        target,
        target_private,
    )

    first = cutover.reopen_source(
        pairing=pairing,
        makerspace=source,
        receipt_envelope=abort_envelope,
        actor=actor,
    )
    second = cutover.reopen_source(
        pairing=pairing,
        makerspace=source,
        receipt_envelope=abort_envelope,
        actor=actor,
    )

    source.refresh_from_db()
    gate.refresh_from_db()
    assert first == second == abort_envelope
    assert source.archived_at is None
    assert gate.state == SourceMigrationGate.State.OPEN
    assert gate.fencing_token == 2
    assert ReceiptConsumption.objects.filter(
        purpose=ReceiptConsumption.Purpose.REOPEN_SOURCE
    ).count() == 1
