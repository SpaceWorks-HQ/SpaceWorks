from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.models import BulkImportJob
from apps.admin_api.tasks import process_bulk_import_job
from apps.backup.models import (
    B1FenceContinuity,
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.hardware_requests.tasks import send_return_reminders_task
from apps.inventory.models import InventoryProduct
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.backup.e7_partition_test_helpers import digest


pytestmark = pytest.mark.django_db(transaction=True)


def _operation():
    operation_id = uuid4()
    return B1RestoreOperationState.objects.create(
        operation_id=operation_id,
        artifact_id=uuid4(),
        capture_id=uuid4(),
        main_component_id=uuid4(),
        outer_ciphertext_sha256=digest(f"outer-{operation_id}"),
        outer_manifest_sha256=digest(f"manifest-{operation_id}"),
        source_proof_sha256=digest(f"proof-{operation_id}"),
        sibling_database_name=f"e7_{operation_id.hex[:20]}",
        sibling_database_oid=7701,
        sibling_server_identity="postgresql:160010:not-restored",
    )


def _component(operation, makerspace_id):
    return B1RestoreComponentState.objects.create(
        operation_id=operation.pk,
        artifact_id=operation.artifact_id,
        capture_id=operation.capture_id,
        component_id=uuid4(),
        makerspace_id_snapshot=makerspace_id,
        ciphertext_sha256=digest(f"component-{makerspace_id}"),
        state=B1RestoreComponentState.State.PENDING,
    )


def _space(slug):
    return Makerspace.objects.create(name=slug, slug=f"{slug}-{uuid4().hex}")


def _manager(space, label):
    actor = User.objects.create_user(
        username=f"{label}-{uuid4().hex}",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return actor


def test_component_state_identity_is_immutable_and_state_is_closed_enum():
    operation = _operation()
    component = _component(operation, 7701)

    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreComponentState.objects.filter(pk=component.pk).update(
            artifact_id=uuid4(), capture_id=uuid4(), component_id=uuid4()
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        B1RestoreComponentState.objects.filter(pk=component.pk).update(state="empty")

    component.refresh_from_db()
    assert component.artifact_id == operation.artifact_id
    assert component.capture_id == operation.capture_id
    assert component.state in {
        "pending", "dependency_wait", "merging", "restored", "failed"
    }


def test_only_one_non_restored_component_state_exists_per_sovereign_makerspace():
    first = _operation()
    _component(first, 7702)
    second = _operation()

    with pytest.raises(IntegrityError), transaction.atomic():
        _component(second, 7702)


def test_readable_main_tenant_is_served_while_pending_tenant_fails_closed():
    ordinary = _space("e7-readable-main")
    pending = _space("e7-pending-slice")
    actor = _manager(ordinary, "e7-main-manager")
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=pending,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    _component(_operation(), pending.pk)

    assert get_public_makerspace(ordinary.slug) == ordinary
    assert rbac.can(actor, rbac.Action.VIEW_INVENTORY, ordinary.pk) is True
    assert rbac.can(actor, rbac.Action.VIEW_INVENTORY, pending.pk) is False
    with pytest.raises(Http404):
        get_public_makerspace(pending.slug)


def test_celery_worker_cannot_claim_or_apply_work_for_pending_tenant():
    pending = _space("e7-pending-worker")
    actor = _manager(pending, "e7-worker-manager")
    _component(_operation(), pending.pk)
    job = BulkImportJob.objects.create(
        makerspace=pending,
        actor=actor,
        mode=BulkImportJob.Mode.APPLY,
        rows=[{
            "name": "Must not materialize while opaque",
            "total_quantity": "1",
            "available_quantity": "1",
        }],
    )

    refusal = None
    try:
        process_bulk_import_job.apply(args=(job.pk,)).get(propagate=True)
    except Exception as exc:  # A boundary exception is also a valid fail-closed result.
        refusal = str(exc).lower()

    job.refresh_from_db()
    assert job.status in {BulkImportJob.Status.PENDING, BulkImportJob.Status.FAILED}
    reason = refusal or job.error.lower()
    assert "not restored" in reason or "pending" in reason
    assert not InventoryProduct.objects.filter(
        makerspace=pending, name="Must not materialize while opaque"
    ).exists()


def test_scheduled_return_reminder_skips_pending_tenant(monkeypatch):
    pending = _space("e7-pending-cron")
    _component(_operation(), pending.pk)
    requester = User.objects.create_user(
        username=f"e7-overdue-{uuid4().hex}",
        email="e7-overdue@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    product = InventoryProduct.objects.create(
        makerspace=pending,
        name="Opaque loan",
        total_quantity=1,
        available_quantity=0,
        issued_quantity=1,
    )
    request = HardwareRequest.objects.create(
        makerspace=pending,
        requester=requester,
        requester_username=requester.username,
        requester_contact_email=requester.email,
        status=HardwareRequest.Status.ISSUED,
        return_due_at=timezone.now() - timedelta(minutes=5),
    )
    HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=1,
        accepted_quantity=1,
        issued_quantity=1,
    )
    delivered = []
    monkeypatch.setattr(
        "apps.hardware_requests.services_return_reminders.notifications.notify_return_due",
        lambda item: delivered.append(item.pk) or True,
    )
    monkeypatch.setattr(
        "apps.hardware_requests.services_return_reminders.emit_notification",
        lambda *_args, **_kwargs: None,
    )

    result = send_return_reminders_task()

    request.refresh_from_db()
    assert result == {"sent": 0, "skipped": 1}
    assert delivered == []
    assert request.return_reminder_sent_at is None


def test_pending_identity_is_neither_empty_nor_newly_creatable():
    operation = _operation()
    pending_id = 9_700_001
    component = _component(operation, pending_id)
    identity = digest("makerspace-low-entropy-fence")
    definition = digest("makerspace-insert-definition")
    B1ReservationEntry.objects.create(
        operation_id=operation.pk,
        component_id=component.component_id,
        registry_identity=identity,
        kind=B1ReservationEntry.Kind.BROAD_FENCE,
        definition_sha256=definition,
        safe_payload={
            "schema": "public", "table": "makerspaces_makerspace",
            "operations": ["insert", "update"],
            "component_ids": [str(component.component_id)],
            "definition_sha256": definition,
        },
        installed_at=timezone.now(),
        catalog_verified_at=timezone.now(),
    )
    B1FenceContinuity.objects.create(
        operation_id=operation.pk,
        registry_identity=identity,
        definition_sha256=definition,
        trigger_oids=[9700001],
    )
    superadmin = User.objects.create_superuser(
        username=f"e7-pending-superadmin-{uuid4().hex}", password="secret"
    )

    assert rbac.can(superadmin, rbac.Action.MANAGE_MAKERSPACE, pending_id) is False
    with pytest.raises(DatabaseError), transaction.atomic():
        Makerspace.objects.create(
            pk=pending_id, name="Replacement empty tenant",
            slug=f"replacement-{uuid4().hex}",
        )
