import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.accounts import rbac
from apps.accounts.rbac import Action
from apps.backup.models import B1RestoreOperationState
from apps.backup.not_restored import TenantNotRestored
from apps.machines.role_scope import NOTHING, manage_scope_for
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import is_servable, servable_queryset
from apps.tenant_migration.gate_runtime import assert_write_allowed, fanout_tenant_write
from tests.backup.e7_reservation_test_helpers import (
    assert_database_rejects,
    persist_restore_state,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _component_fact():
    return {"component_ids": [str(uuid.uuid4())]}


def test_restore_operation_stage_can_only_advance_one_database_step():
    operation_id, _component_id = persist_restore_state(_component_fact())

    assert_database_rejects(lambda: B1RestoreOperationState.objects.filter(
        pk=operation_id
    ).update(stage=B1RestoreOperationState.Stage.STATE_REHYDRATED))

    assert B1RestoreOperationState.objects.filter(pk=operation_id).update(
        stage=B1RestoreOperationState.Stage.CATALOG_VERIFIED
    ) == 1


def test_pending_tenant_fails_closed_in_rbac_machine_and_worker_scopes():
    space = Makerspace.objects.create(
        name="E7 pending tenant", slug=f"e7-pending-{uuid.uuid4().hex}"
    )
    actor = get_user_model().objects.create_superuser(
        username=f"e7-super-{uuid.uuid4().hex}", password="not-used"
    )
    persist_restore_state(_component_fact(), makerspace_id=space.pk)

    assert not rbac.can(actor, Action.MANAGE_MAKERSPACE, space.pk)
    assert manage_scope_for(actor, space.pk) == NOTHING
    assert not is_servable(space)
    assert not servable_queryset().filter(pk=space.pk).exists()
    with pytest.raises(TenantNotRestored):
        assert_write_allowed(space.pk)

    counts = {"processed": 0, "skipped": 0}
    with fanout_tenant_write(
        space.pk, operation="e7_pending_worker_probe", counts=counts
    ) as should_process:
        counts["processed"] += int(should_process)
    assert counts == {"processed": 0, "skipped": 1}


def test_pending_snapshot_cannot_be_recreated_as_an_empty_makerspace():
    with connection.cursor() as cursor:
        cursor.execute("SELECT COALESCE(max(id), 0) + 1000 FROM makerspaces_makerspace")
        reserved_id = cursor.fetchone()[0]
    persist_restore_state(_component_fact(), makerspace_id=reserved_id)

    assert_database_rejects(lambda: Makerspace.objects.create(
        id=reserved_id,
        name="False empty tenant",
        slug=f"e7-false-empty-{uuid.uuid4().hex}",
    ))
