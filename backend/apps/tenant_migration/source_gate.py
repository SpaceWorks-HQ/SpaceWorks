"""Lease, fencing-token, and quiescence transitions for source migration."""

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.tenant_migration.gate_errors import (
    SourceMigrationGateClosed,
    SourceMigrationOwnershipError,
    SourceMigrationRecoveryError,
)
from apps.tenant_migration.gate_locks import (
    acquire_exclusive,
    acquire_unscoped_writer_exclusive,
    try_acquire_exclusive,
)
from apps.tenant_migration.models_source_gate import SourceMigrationGate


@dataclass(frozen=True)
class GateLease:
    makerspace_id: int
    owner_id: uuid.UUID
    fencing_token: int
    state: str
    lease_expires_at: object


@dataclass(frozen=True)
class GateRecovery:
    previous_owner_id: uuid.UUID
    fencing_token: int


def claim(
    makerspace, actor, *, owner_id=None, fencing_token=None, now=None
):
    """Close the gate after draining pre-existing shared-lock writers."""
    owner_id = owner_id or SourceMigrationGate.new_owner_id()
    now = now or timezone.now()
    with transaction.atomic():
        # Unscoped HTTP/task writers use this global shared key. Taking it first
        # drains them without changing the tenant-key ordering used by scoped writers.
        acquire_unscoped_writer_exclusive()
        acquire_exclusive(makerspace.pk)
        gate, _ = SourceMigrationGate.objects.select_for_update().get_or_create(
            makerspace_id=makerspace.pk
        )
        if gate.state != SourceMigrationGate.State.OPEN:
            if gate.owner_id == owner_id:
                if fencing_token != gate.fencing_token:
                    raise SourceMigrationOwnershipError(
                        "The source migration fencing token is stale."
                    )
                _require_live_owner(gate, owner_id, gate.fencing_token, now)
                return _lease(gate)
            raise SourceMigrationGateClosed(
                "This makerspace already has an active migration owner."
            )

        drain_seconds = max(
            0, int(settings.TENANT_MIGRATION_PRESIGN_DRAIN_SECONDS)
        )
        gate.state = SourceMigrationGate.State.DRAINING
        gate.owner_id = owner_id
        gate.fencing_token += 1
        gate.actor = actor
        gate.heartbeat_at = now
        gate.lease_expires_at = now + timedelta(
            seconds=settings.TENANT_MIGRATION_GATE_LEASE_SECONDS
        )
        gate.presign_drain_until = now + timedelta(seconds=drain_seconds)
        gate.quiesced_at = None
        gate.reopened_at = None
        gate.save()
        audit.record(
            actor,
            "tenant_migration.source_gate_closed",
            makerspace=makerspace,
            target=gate,
            meta={
                "owner_id": str(owner_id),
                "fencing_token": gate.fencing_token,
                "presign_drain_seconds": drain_seconds,
            },
        )
        return _lease(gate)


def heartbeat(lease, *, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        gate = SourceMigrationGate.objects.select_for_update().get(
            makerspace_id=lease.makerspace_id
        )
        _require_live_owner(gate, lease.owner_id, lease.fencing_token, now)
        gate.heartbeat_at = now
        gate.lease_expires_at = now + timedelta(
            seconds=settings.TENANT_MIGRATION_GATE_LEASE_SECONDS
        )
        gate.save(update_fields=("heartbeat_at", "lease_expires_at", "updated_at"))
        return _lease(gate)


@contextmanager
def quiesced_snapshot(
    makerspace, actor, *, owner_id=None, fencing_token=None, sleep=time.sleep
):
    """Yield inside the repeatable-read snapshot that establishes quiescence."""
    lease = claim(
        makerspace,
        actor,
        owner_id=owner_id,
        fencing_token=fencing_token,
    )
    gate = SourceMigrationGate.objects.only("presign_drain_until").get(
        makerspace_id=makerspace.pk
    )
    remaining = max(
        0.0, (gate.presign_drain_until - timezone.now()).total_seconds()
    )
    if remaining:
        sleep(remaining)

    # Stamp QUIESCED in a short row-locking transaction. Object storage and export
    # work happen only after this commits, so no external I/O runs under this row lock.
    with transaction.atomic():
        acquire_exclusive(makerspace.pk)
        gate = SourceMigrationGate.objects.select_for_update().get(
            makerspace_id=makerspace.pk
        )
        _require_live_owner(
            gate, lease.owner_id, lease.fencing_token, timezone.now()
        )
        if gate.state == SourceMigrationGate.State.DRAINING:
            gate.state = SourceMigrationGate.State.QUIESCED
            gate.quiesced_at = timezone.now()
            gate.save(update_fields=("state", "quiesced_at", "updated_at"))
            audit.record(
                actor,
                "tenant_migration.source_quiesced",
                makerspace=makerspace,
                target=gate,
                meta={
                    "owner_id": str(lease.owner_id),
                    "fencing_token": lease.fencing_token,
                },
            )
        elif gate.state != SourceMigrationGate.State.QUIESCED:
            raise SourceMigrationOwnershipError(
                "The source gate is not resumable at the snapshot step."
            )

    # The persistent closed state refuses new writers between the two transactions.
    # Reacquiring exclusive before the first snapshot query proves the writer set is
    # still empty, without retaining a row lock during object-storage I/O.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        acquire_exclusive(makerspace.pk)
        gate = SourceMigrationGate.objects.get(makerspace_id=makerspace.pk)
        _require_live_owner(
            gate, lease.owner_id, lease.fencing_token, timezone.now()
        )
        if gate.state != SourceMigrationGate.State.QUIESCED:
            raise SourceMigrationOwnershipError(
                "The source gate changed before its snapshot opened."
            )
        yield _lease(gate)


def mark_migrated_out(makerspace_id, owner_id, fencing_token, *, actor=None):
    with transaction.atomic():
        acquire_exclusive(makerspace_id)
        gate = SourceMigrationGate.objects.select_for_update().get(
            makerspace_id=makerspace_id
        )
        _require_live_owner(gate, owner_id, fencing_token, timezone.now())
        if gate.state == SourceMigrationGate.State.MIGRATED_OUT:
            return _lease(gate)
        if gate.state != SourceMigrationGate.State.QUIESCED:
            raise SourceMigrationOwnershipError("Source cutover requires quiescence.")
        gate.state = SourceMigrationGate.State.MIGRATED_OUT
        gate.save(update_fields=("state", "updated_at"))
        audit.record(
            actor or gate.actor,
            "tenant_migration.source_gate_migrated_out",
            makerspace=gate.makerspace,
            target=gate,
            meta={
                "owner_id": str(owner_id),
                "fencing_token": fencing_token,
                "outcome": "migrated_out",
            },
        )
        return _lease(gate)


def recover_expired(makerspace, actor, *, now=None):
    """Reopen only an orphaned pre-cutover gate while proving no lock owner lives."""
    now = now or timezone.now()
    with transaction.atomic():
        if not try_acquire_exclusive(makerspace.pk):
            raise SourceMigrationRecoveryError(
                "The source migration exclusive lock is still held."
            )
        gate = SourceMigrationGate.objects.select_for_update().get(
            makerspace_id=makerspace.pk
        )
        if gate.state == SourceMigrationGate.State.OPEN:
            return None
        if gate.state == SourceMigrationGate.State.MIGRATED_OUT:
            raise SourceMigrationRecoveryError(
                "A migrated-out source requires a signed target abort receipt."
            )
        if gate.lease_expires_at is None or gate.lease_expires_at >= now:
            raise SourceMigrationRecoveryError(
                "The source migration owner still has a live lease."
            )
        return _open(
            gate, actor, action="tenant_migration.source_gate_recovered"
        )


@transaction.atomic
def reopen_after_verified_abort(makerspace, actor):
    acquire_exclusive(makerspace.pk)
    gate = SourceMigrationGate.objects.select_for_update().filter(
        makerspace_id=makerspace.pk
    ).first()
    if gate is None or gate.state == SourceMigrationGate.State.OPEN:
        return False
    _open(gate, actor, action="tenant_migration.source_gate_reopened")
    return True


def _open(gate, actor, *, action):
    previous_owner = gate.owner_id
    previous_token = gate.fencing_token
    gate.state = SourceMigrationGate.State.OPEN
    gate.owner_id = None
    gate.fencing_token += 1
    gate.actor = actor
    gate.heartbeat_at = None
    gate.lease_expires_at = None
    gate.presign_drain_until = None
    gate.reopened_at = timezone.now()
    gate.save()
    audit.record(
        actor,
        action,
        makerspace=gate.makerspace,
        target=gate,
        meta={
            "owner_id": str(previous_owner),
            "fencing_token": previous_token,
        },
    )
    return GateRecovery(previous_owner, previous_token)


def _require_live_owner(gate, owner_id, fencing_token, now):
    if gate.owner_id != owner_id or gate.fencing_token != fencing_token:
        raise SourceMigrationOwnershipError("The source migration owner is stale.")
    if gate.lease_expires_at is None or gate.lease_expires_at <= now:
        raise SourceMigrationOwnershipError("The source migration lease has expired.")


def _lease(gate):
    return GateLease(
        makerspace_id=gate.makerspace_id,
        owner_id=gate.owner_id,
        fencing_token=gate.fencing_token,
        state=gate.state,
        lease_expires_at=gate.lease_expires_at,
    )
