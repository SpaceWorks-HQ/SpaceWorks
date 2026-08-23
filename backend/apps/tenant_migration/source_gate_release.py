"""Live fenced release for a successful non-cutover source capture."""

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit

from .gate_errors import SourceMigrationOwnershipError
from .gate_locks import acquire_exclusive
from .models_source_gate import SourceMigrationGate
from .source_gate import _require_live_owner


def release_after_copy_capture(lease, *, actor=None):
    """Reopen only the live owner of a completed `copy_capture` lease."""
    with transaction.atomic():
        acquire_exclusive(lease.makerspace_id)
        gate = SourceMigrationGate.objects.select_for_update().get(
            makerspace_id=lease.makerspace_id
        )
        _require_live_owner(
            gate,
            lease.owner_id,
            lease.fencing_token,
            timezone.now(),
        )
        if gate.state != SourceMigrationGate.State.QUIESCED:
            raise SourceMigrationOwnershipError(
                "A copy capture can release only a quiesced source gate."
            )
        if gate.purpose != SourceMigrationGate.Purpose.COPY_CAPTURE:
            raise SourceMigrationOwnershipError(
                "The source gate is not owned for a copy capture."
            )
        gate.state = SourceMigrationGate.State.OPEN
        gate.purpose = SourceMigrationGate.Purpose.MIGRATION
        gate.owner_id = None
        gate.fencing_token += 1
        gate.actor = actor or gate.actor
        gate.heartbeat_at = None
        gate.lease_expires_at = None
        gate.presign_drain_until = None
        gate.reopened_at = timezone.now()
        gate.save()
        audit.record(
            actor or gate.actor,
            "tenant_migration.source_gate_capture_released",
            makerspace=gate.makerspace,
            target=gate,
            meta={
                "owner_id": str(lease.owner_id),
                "fencing_token": lease.fencing_token,
                "purpose": SourceMigrationGate.Purpose.COPY_CAPTURE,
            },
        )
        return gate.fencing_token
