from pathlib import Path
import uuid

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import User
from apps.backup.models import (
    B1FenceContinuity,
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.backup.e7_partition_test_helpers import digest


pytestmark = pytest.mark.django_db(transaction=True)

ORDERED_STAGES = (
    B1RestoreOperationState.Stage.VERIFIED,
    B1RestoreOperationState.Stage.MAIN_RESTORED,
    B1RestoreOperationState.Stage.ROLES_RECREATED,
    B1RestoreOperationState.Stage.STATE_REHYDRATED,
    B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED,
    B1RestoreOperationState.Stage.CATALOG_VERIFIED,
    B1RestoreOperationState.Stage.OBJECTS_VERIFIED,
    B1RestoreOperationState.Stage.QUARANTINE_VERIFIED,
    B1RestoreOperationState.Stage.CUTOVER_READY,
)


def _operation(*, stage=B1RestoreOperationState.Stage.VERIFIED):
    operation_id = uuid.uuid4()
    operation = B1RestoreOperationState.objects.create(
        operation_id=operation_id,
        artifact_id=uuid.uuid4(),
        capture_id=uuid.uuid4(),
        main_component_id=uuid.uuid4(),
        outer_ciphertext_sha256=digest(f"outer-{operation_id}"),
        outer_manifest_sha256=digest(f"manifest-{operation_id}"),
        source_proof_sha256=digest(f"proof-{operation_id}"),
        sibling_database_name=f"e7_{operation_id.hex[:20]}",
        sibling_database_oid=701,
        sibling_server_identity="postgresql:160010:e7-target",
    )
    target_index = ORDERED_STAGES.index(stage)
    for next_stage in ORDERED_STAGES[1:target_index + 1]:
        B1RestoreOperationState.objects.filter(pk=operation.pk).update(
            stage=next_stage
        )
    operation.refresh_from_db()
    return operation


def _pending_component(operation, makerspace_id):
    return B1RestoreComponentState.objects.create(
        operation_id=operation.operation_id,
        artifact_id=operation.artifact_id,
        capture_id=operation.capture_id,
        component_id=uuid.uuid4(),
        makerspace_id_snapshot=makerspace_id,
        ciphertext_sha256=digest(f"slice-{makerspace_id}"),
        state=B1RestoreComponentState.State.PENDING,
    )


def test_restore_operation_declares_the_specified_nine_step_order():
    declared = tuple(
        value for value, _label in B1RestoreOperationState.Stage.choices
        if value != B1RestoreOperationState.Stage.FAILED
    )
    assert declared == ORDERED_STAGES


@pytest.mark.parametrize(
    ("start", "skipped"),
    tuple(zip(ORDERED_STAGES, ORDERED_STAGES[2:])),
)
def test_database_rejects_every_skipped_pre_cutover_step(start, skipped):
    operation = _operation(stage=start)

    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreOperationState.objects.filter(pk=operation.pk).update(stage=skipped)

    operation.refresh_from_db()
    assert operation.stage == start


def test_roles_and_grants_stage_cannot_be_skipped_before_any_later_django_stage():
    operation = _operation(stage=B1RestoreOperationState.Stage.MAIN_RESTORED)

    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreOperationState.objects.filter(pk=operation.pk).update(
            stage=B1RestoreOperationState.Stage.STATE_REHYDRATED
        )

    operation.refresh_from_db()
    assert operation.stage == B1RestoreOperationState.Stage.MAIN_RESTORED


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC BUG: scripts/restore.sh runs post-restore Django before recreating "
        "the database roles and grants omitted by --no-owner/--no-acl"
    ),
)
def test_host_supervisor_recreates_roles_with_psql_before_post_restore_django():
    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "restore.sh"
    ).read_text(encoding="utf-8")
    replaced = script.index('say "Replacing the database."')
    post_restore = script[replaced:]
    first_django = post_restore.index('control rehydrate "$RESTORE_ID"')
    role_statements = [
        index for token in ("CREATE ROLE", "ALTER ROLE", "GRANT ")
        if (index := post_restore.find(token)) >= 0
    ]

    assert role_statements, (
        "The --no-owner/--no-acl restore never recreates database roles and grants."
    )
    assert max(role_statements) < first_django


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC BUG: scripts/restore.sh still replaces the routable database in place "
        "instead of using the Lane E B1 non-routable sibling protocol"
    ),
)
def test_b1_host_restore_uses_a_non_routable_sibling_until_cutover():
    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "restore.sh"
    ).read_text(encoding="utf-8")

    assert "spaceworks-lane-e-b1-v1" in script
    assert "sibling" in script.lower()
    assert "B1RestoreOperationState" in script or "b1-restore" in script.lower()


def _reservation(component, kind, *, installed):
    identity = digest(f"{kind}-{component.component_id}")
    return B1ReservationEntry.objects.create(
        operation_id=component.operation_id,
        component_id=component.component_id,
        registry_identity=identity,
        kind=kind,
        definition_sha256=digest(f"definition-{identity}"),
        safe_payload={
            "component_ids": [str(component.component_id)],
            "definition_sha256": digest(f"definition-{identity}"),
        },
        installed_at=timezone.now() if installed else None,
    )


def _crashed_boundary(boundary):
    space = Makerspace.objects.create(
        name=f"E7 crash {boundary}", slug=f"e7-crash-{boundary}-{uuid.uuid4().hex}"
    )
    actor = User.objects.create_user(
        username=f"e7-crash-{boundary}-{uuid.uuid4().hex}",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=actor, makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    operation = _operation(stage=B1RestoreOperationState.Stage.STATE_REHYDRATED)
    component = _pending_component(operation, space.pk)
    if boundary == "reservation-declared":
        _reservation(component, B1ReservationEntry.Kind.COMMITMENT, installed=False)
    elif boundary in {"reservation-installed", "fence-declared", "fence-installed"}:
        _reservation(component, B1ReservationEntry.Kind.COMMITMENT, installed=True)
    if boundary == "fence-declared":
        _reservation(component, B1ReservationEntry.Kind.BROAD_FENCE, installed=False)
    elif boundary == "fence-installed":
        _reservation(component, B1ReservationEntry.Kind.BROAD_FENCE, installed=True)
    return operation, actor, space


@pytest.mark.parametrize(
    "boundary",
    (
        "before-first-reservation", "reservation-declared",
        "reservation-installed", "fence-declared", "fence-installed",
    ),
)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC BUG: the restore-operation stage trigger accepts "
        "enforcement_installed without proving every reservation and fence installed"
    ),
)
def test_crash_at_every_installation_boundary_fails_closed_without_a_fence_gap(
    boundary,
):
    operation, actor, space = _crashed_boundary(boundary)

    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreOperationState.objects.filter(pk=operation.pk).update(
            stage=B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED
        )

    operation.refresh_from_db()
    assert operation.stage == B1RestoreOperationState.Stage.STATE_REHYDRATED
    assert rbac.can(actor, rbac.Action.VIEW_INVENTORY, space.pk) is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC BUG: the restore-operation stage trigger accepts catalog_verified "
        "without a matching continuous enabled-fence record"
    ),
)
def test_catalog_verification_requires_continuous_enabled_fence_evidence():
    operation = _operation(
        stage=B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED
    )
    component = _pending_component(operation, 9701)
    fence = _reservation(component, B1ReservationEntry.Kind.BROAD_FENCE, installed=True)
    fence.catalog_verified_at = timezone.now()
    fence.save(update_fields=("catalog_verified_at",))
    assert not B1FenceContinuity.objects.filter(
        operation_id=operation.pk, registry_identity=fence.registry_identity
    ).exists()

    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreOperationState.objects.filter(pk=operation.pk).update(
            stage=B1RestoreOperationState.Stage.CATALOG_VERIFIED
        )


def test_continuity_evidence_cannot_be_deleted_or_disabled_after_installation():
    operation = _operation(
        stage=B1RestoreOperationState.Stage.ENFORCEMENT_INSTALLED
    )
    continuity = B1FenceContinuity.objects.create(
        operation_id=operation.pk,
        registry_identity=digest("continuous-fence"),
        definition_sha256=digest("continuous-definition"),
        trigger_oids=[701, 702],
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        B1FenceContinuity.objects.filter(pk=continuity.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        B1FenceContinuity.objects.filter(pk=continuity.pk).update(enabled=False)

    continuity.refresh_from_db()
    assert continuity.enabled is True
