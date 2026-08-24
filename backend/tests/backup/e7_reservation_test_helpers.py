import hashlib
import uuid

import pytest
from django.db import DatabaseError, models, transaction
from django.utils import timezone

from apps.backup.models import (
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)


DIGEST = "d" * 64


class CommitmentProbe(models.Model):
    id = models.BigAutoField(primary_key=True)
    left_token = models.TextField(null=True)
    right_token = models.TextField(null=True)
    uuid_token = models.UUIDField(null=True)
    active = models.BooleanField(default=True)

    class Meta:
        # Keep this unmanaged SQL probe outside installed app registries so the
        # production model/data-export drift guards do not discover test schema.
        app_label = "e7_test_models"
        managed = False
        db_table = "backup_e7_commitment_probe"


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def persist_active_reservation(fact, kind, *, makerspace_id=7001):
    """Rehydrate the signed fact/state that must drive database enforcement."""

    operation_id, component_id = persist_restore_state(
        fact, makerspace_id=makerspace_id
    )
    identity = fact.get("constraint_identity") or fact.get("registry_identity")
    return B1ReservationEntry.objects.create(
        operation_id=operation_id,
        component_id=component_id,
        registry_identity=identity,
        kind=kind,
        definition_sha256=fact["definition_sha256"],
        safe_payload=fact,
        installed_at=timezone.now(),
        catalog_verified_at=timezone.now(),
    )


def persist_restore_state(fact, *, makerspace_id=7001):
    operation_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    capture_id = uuid.uuid4()
    component_id = uuid.UUID(str(fact["component_ids"][0]))
    B1RestoreOperationState.objects.create(
        operation_id=operation_id,
        artifact_id=artifact_id,
        capture_id=capture_id,
        main_component_id=uuid.uuid4(),
        outer_ciphertext_sha256=DIGEST,
        outer_manifest_sha256=DIGEST,
        source_proof_sha256=DIGEST,
        sibling_database_name="e7_reservation_sibling",
        sibling_database_oid=7001,
        sibling_server_identity="postgresql:e7-test",
        stage=B1RestoreOperationState.Stage.VERIFIED,
    )
    for stage in (
        B1RestoreOperationState.Stage.MAIN_RESTORED,
        B1RestoreOperationState.Stage.ROLES_RECREATED,
        B1RestoreOperationState.Stage.STATE_REHYDRATED,
        B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
    ):
        B1RestoreOperationState.objects.filter(pk=operation_id).update(stage=stage)
    B1RestoreComponentState.objects.create(
        operation_id=operation_id,
        artifact_id=artifact_id,
        capture_id=capture_id,
        component_id=component_id,
        makerspace_id_snapshot=makerspace_id,
        ciphertext_sha256=DIGEST,
        state=B1RestoreComponentState.State.PENDING,
    )
    return operation_id, component_id


def assert_database_rejects(write):
    """Require PostgreSQL, rather than caller validation, to reject a write."""

    try:
        with transaction.atomic():
            write()
    except DatabaseError:
        return
    pytest.fail("PostgreSQL accepted a write covered by an active E7 reservation")
