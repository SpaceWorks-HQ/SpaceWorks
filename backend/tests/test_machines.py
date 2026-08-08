from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.evidence.storage import StorageUnavailable
from apps.inventory.models import InventoryProduct, TrackingMode
from apps.machines import access
from apps.machines.models import (
    Machine,
    MachineConsumable,
    MachineDocument,
    MachineOperator,
    MachineType,
    MachineUsageEntry,
)
from apps.makerspaces import lifecycle as makerspace_lifecycle
from apps.makerspaces.models import MakerspaceMembership
from apps.operations.models import InventoryAdjustment
from apps.warranty.models import Warranty
from tests.return_helpers import authenticated_client, make_member, make_space, make_user
from tests.handout_roles import grant_handout, make_handout_member

pytestmark = pytest.mark.django_db


def test_operator_candidates_return_only_active_members_with_minimal_fields():
    makerspace = enable_machines(make_space('machines-candidates'))
    manager = make_member('machines-candidates-manager', makerspace)
    active = make_handout_member('machines-candidates-active', makerspace)
    active.first_name = 'Active'
    active.last_name = 'Member'
    active.email = 'private@example.test'
    active.telegram_user_id = 'private-telegram'
    active.external_checkin_user_id = 'private-checkin'
    active.save()
    restricted = make_handout_member('machines-candidates-restricted', makerspace)
    restricted.access_status = User.AccessStatus.RESTRICTED
    restricted.save(update_fields=['access_status'])
    inactive = make_user(
        'machines-candidates-inactive',
        access_status=User.AccessStatus.ACTIVE,
        is_active=False,
    )
    grant_handout(inactive, makerspace)
    machine = make_machine(makerspace)

    response = authenticated_client(manager).get(
        reverse('admin-machine-operator-candidates', kwargs={'pk': machine.id})
    )

    assert response.status_code == 200
    assert {row['user_id'] for row in response.data} == {manager.id, active.id}
    assert next(row for row in response.data if row['user_id'] == active.id) == {
        'user_id': active.id,
        'username': active.username,
        'display_name': 'Active Member',
    }
    assert all(
        set(row) == {'user_id', 'username', 'display_name'}
        for row in response.data
    )
    assert all(
        key not in row
        for row in response.data
        for key in (
            'email',
            'telegram_user_id',
            'external_checkin_user_id',
            'access_status',
            'restriction_reason',
        )
    )


def test_operator_candidates_forbid_operate_only_operator():
    makerspace = enable_machines(make_space('machines-candidates-forbidden'))
    operator = make_handout_member('machines-candidates-operate', makerspace)
    machine = make_machine(makerspace)
    MachineOperator.objects.create(
        machine=machine,
        user=operator,
        access_level=MachineOperator.AccessLevel.OPERATE,
    )

    response = authenticated_client(operator).get(
        reverse('admin-machine-operator-candidates', kwargs={'pk': machine.id})
    )

    assert response.status_code == 403


def test_operator_candidates_are_404_across_tenants():
    makerspace_a = enable_machines(make_space('machines-candidates-tenant-a'))
    makerspace_b = enable_machines(make_space('machines-candidates-tenant-b'))
    manager_a = make_member('machines-candidates-manager-a', makerspace_a)
    machine_b = make_machine(makerspace_b)

    response = authenticated_client(manager_a).get(
        reverse('admin-machine-operator-candidates', kwargs={'pk': machine_b.id})
    )

    assert response.status_code == 404


def test_operator_candidates_respect_disabled_machines_module():
    makerspace = enable_machines(make_space('machines-candidates-module'))
    manager = make_member('machines-candidates-module-manager', makerspace)
    machine = make_machine(makerspace)
    makerspace.enabled_modules = [
        module for module in makerspace.enabled_modules if module != 'machines'
    ]
    makerspace.save(update_fields=['enabled_modules'])

    response = authenticated_client(manager).get(
        reverse('admin-machine-operator-candidates', kwargs={'pk': machine.id})
    )

    assert response.status_code == 400


def test_machine_capability_matrix():
    makerspace = enable_machines(make_space('machines-capability-matrix'))
    machine = make_machine(makerspace)
    operate = make_handout_member('machines-capability-operate', makerspace)
    manage = make_handout_member('machines-capability-manage', makerspace)
    full = make_handout_member('machines-capability-full', makerspace)
    type_manager = make_member(
        'machines-capability-type-manager',
        makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
    )
    admin = make_member('machines-capability-admin', makerspace)
    MachineOperator.objects.bulk_create(
        [
            MachineOperator(
                machine=machine,
                user=operate,
                access_level=MachineOperator.AccessLevel.OPERATE,
            ),
            MachineOperator(
                machine=machine,
                user=manage,
                access_level=MachineOperator.AccessLevel.MANAGE,
            ),
            MachineOperator(
                machine=machine,
                user=full,
                access_level=MachineOperator.AccessLevel.FULL,
            ),
        ]
    )

    assert access.machine_capabilities(operate, machine) == {
        'can_operate': True,
        'can_edit': False,
        'can_delegate': False,
        'can_retire': False,
        'can_unretire': False,
    }
    assert access.machine_capabilities(manage, machine) == {
        'can_operate': True,
        'can_edit': True,
        'can_delegate': False,
        'can_retire': False,
        'can_unretire': False,
    }
    assert access.machine_capabilities(full, machine) == {
        'can_operate': True,
        'can_edit': True,
        'can_delegate': True,
        'can_retire': True,
        'can_unretire': False,
    }
    all_capabilities = {
        'can_operate': True,
        'can_edit': True,
        'can_delegate': True,
        'can_retire': True,
        'can_unretire': True,
    }
    assert access.machine_capabilities(type_manager, machine) == all_capabilities
    assert access.machine_capabilities(admin, machine) == all_capabilities


def test_machine_list_query_count_is_constant_as_machines_increase(
    django_assert_num_queries,
):
    makerspace = enable_machines(make_space('machines-list-query-count'))
    manager = make_member('machines-list-query-count-manager', makerspace)
    first = make_machine(makerspace, name='Query Machine One')
    MachineUsageEntry.objects.create(
        machine=first,
        hours=Decimal('1.25'),
        logged_by=manager,
    )
    client = authenticated_client(manager)
    url = reverse('admin-machines', kwargs={'makerspace_id': makerspace.id})

    with CaptureQueriesContext(connection) as captured:
        first_response = client.get(url)
    assert first_response.status_code == 200
    first_count = len(captured)
    second = make_machine(makerspace, name='Query Machine Two')
    MachineUsageEntry.objects.create(
        machine=second,
        hours=Decimal('2.50'),
        logged_by=manager,
    )

    with django_assert_num_queries(first_count):
        second_response = client.get(url)

    assert second_response.status_code == 200
    assert {
        Decimal(str(row['usage_hours']))
        for row in response_rows(second_response)
    } == {Decimal('1.25'), Decimal('2.50')}


@pytest.fixture(autouse=True)
def mock_machine_document_storage(monkeypatch):
    monkeypatch.setattr("apps.machines.storage.finalize_upload", lambda key, max_bytes: 123)
    monkeypatch.setattr(
        "apps.machines.storage.validate_machine_object",
        lambda key: SimpleNamespace(size=123, content_type="application/pdf"),
    )
    monkeypatch.setattr(
        "apps.machines.storage.presigned_upload",
        lambda key, content_type: {"url": "http://x", "fields": {}},
    )
    monkeypatch.setattr(
        "apps.machines.storage.presigned_get_url", lambda key: "http://signed"
    )
    monkeypatch.setattr("apps.machines.storage.delete_object", lambda key: None)
    monkeypatch.setattr("apps.machines.storage.ext_for", lambda *args: "pdf")
    monkeypatch.setattr(
        "apps.machines.storage.machine_object_key",
        lambda makerspace_id, ext: f"machines/{makerspace_id}/x.pdf",
    )


def enable_machines(makerspace):
    enabled = set(makerspace.enabled_modules or [])
    enabled.add("machines")
    makerspace.enabled_modules = sorted(enabled)
    makerspace.save(update_fields=["enabled_modules"])
    return makerspace


def global_machine_type(slug="3d_printer"):
    return MachineType.objects.get(makerspace__isnull=True, slug=slug)


def make_machine(makerspace, *, name="Machine One", machine_type=None, created_by=None):
    enable_machines(makerspace)
    return Machine.objects.create(
        makerspace=makerspace,
        machine_type=machine_type or global_machine_type(),
        name=name,
        created_by=created_by,
    )


def machine_payload(machine_type, **overrides):
    payload = {
        "machine_type_id": machine_type.id,
        "name": "Workshop Printer",
        "location": "Fabrication Bay",
        "notes": "General-use machine",
        "firmware_version": "1.2.3",
        "camera_feed_url": "https://camera.example.test/feed",
    }
    payload.update(overrides)
    return payload


def response_rows(response):
    if isinstance(response.data, dict) and "results" in response.data:
        return response.data["results"]
    return response.data


def assign_operator(client, machine, user, access_level):
    return client.post(
        reverse("admin-machine-operators", kwargs={"pk": machine.id}),
        {"user_id": user.id, "access_level": access_level},
        format="json",
    )


def machine_image_url(machine):
    return reverse("admin-machine-image", kwargs={"pk": machine.id})


def mock_machine_image_storage(monkeypatch, *, size=123):
    from apps.inventory import public_image_storage

    monkeypatch.setattr(
        public_image_storage,
        "presigned_upload",
        lambda object_key, content_type: {
            "url": "http://minio/public-upload",
            "fields": {"key": object_key, "Content-Type": content_type},
        },
    )
    monkeypatch.setattr(
        public_image_storage,
        "finalize_upload",
        lambda object_key: public_image_storage._finalize_result(object_key, size),
    )
    monkeypatch.setattr(public_image_storage, "sniff_is_valid_image", lambda key: True)
    delete = Mock()
    monkeypatch.setattr(public_image_storage, "delete_object", delete)
    return delete


def test_space_manager_can_create_machine_with_global_type_and_created_by():
    makerspace = enable_machines(make_space("machines-create"))
    manager = make_member("machines-create-manager", makerspace)
    machine_type = global_machine_type()

    response = authenticated_client(manager).post(
        reverse("admin-machines", kwargs={"makerspace_id": makerspace.id}),
        machine_payload(machine_type),
        format="json",
    )

    assert response.status_code == 201
    machine = Machine.objects.get(pk=response.data["id"])
    assert machine.makerspace == makerspace
    assert machine.machine_type == machine_type
    assert machine.created_by == manager


def test_guest_admin_without_machine_authority_gets_403_on_list():
    makerspace = enable_machines(make_space("machines-guest-list"))
    guest = make_handout_member("machines-guest-list-user", makerspace)

    response = authenticated_client(guest).get(
        reverse("admin-machines", kwargs={"makerspace_id": makerspace.id})
    )

    assert response.status_code == 403


def test_print_manager_can_create_and_see_only_managed_3d_printer_type():
    makerspace = enable_machines(make_space("machines-print-manager"))
    print_manager = make_member(
        "machines-print-manager-user",
        makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
    )
    printer_type = global_machine_type()
    laser_type = global_machine_type("laser_cutter")
    client = authenticated_client(print_manager)
    list_url = reverse("admin-machines", kwargs={"makerspace_id": makerspace.id})

    created = client.post(list_url, machine_payload(printer_type), format="json")
    denied = client.post(
        list_url,
        machine_payload(laser_type, name="Laser Cutter"),
        format="json",
    )
    listed = client.get(list_url)

    assert created.status_code == 201
    assert denied.status_code == 403
    assert listed.status_code == 200
    assert [row["id"] for row in response_rows(listed)] == [created.data["id"]]


def test_machine_detail_is_404_across_tenants():
    makerspace_a = enable_machines(make_space("machines-tenant-a"))
    makerspace_b = enable_machines(make_space("machines-tenant-b"))
    manager_a = make_member("machines-tenant-a-manager", makerspace_a)
    machine_b = make_machine(makerspace_b)

    response = authenticated_client(manager_a).get(
        reverse("admin-machine-detail", kwargs={"pk": machine_b.id})
    )

    assert response.status_code == 404

def test_operator_access_levels_bound_operate_and_manage_actions():
    makerspace = enable_machines(make_space("machines-operator-levels"))
    manager = make_member("machines-operator-manager", makerspace)
    operator = make_handout_member("machines-operator-user", makerspace)
    machine = make_machine(makerspace)
    manager_client = authenticated_client(manager)
    operator_client = authenticated_client(operator)

    assigned = assign_operator(manager_client, machine, operator, "operate")
    status_response = operator_client.post(
        reverse("admin-machine-set-status", kwargs={"pk": machine.id}),
        {"status": "running"},
        format="json",
    )
    usage_response = operator_client.post(
        reverse("admin-machine-usage", kwargs={"pk": machine.id}),
        {"hours": "1.25", "note": "Training run"},
        format="json",
    )
    error_response = operator_client.post(
        reverse("admin-machine-error-logs", kwargs={"pk": machine.id}),
        {"severity": "warning", "message": "Nozzle temperature drift"},
        format="json",
    )
    patch_denied = operator_client.patch(
        reverse("admin-machine-detail", kwargs={"pk": machine.id}),
        {"location": "Restricted Bay"},
        format="json",
    )
    promoted = manager_client.patch(
        reverse(
            "admin-machine-operator-detail",
            kwargs={"pk": machine.id, "user_pk": operator.id},
        ),
        {"access_level": "manage"},
        format="json",
    )
    patch_allowed = operator_client.patch(
        reverse("admin-machine-detail", kwargs={"pk": machine.id}),
        {"location": "Restricted Bay"},
        format="json",
    )

    assert assigned.status_code == 201
    assert status_response.status_code == 200
    assert usage_response.status_code == 201
    assert error_response.status_code == 201
    assert patch_denied.status_code == 403
    assert promoted.status_code == 200
    assert patch_allowed.status_code == 200
    assert patch_allowed.data["location"] == "Restricted Bay"


def test_full_operator_can_delegate_non_full_and_retire_but_cannot_grant_full():
    makerspace = enable_machines(make_space("machines-full-operator"))
    manager = make_member("machines-full-manager", makerspace)
    full_operator = make_handout_member("machines-full-user", makerspace)
    target = make_handout_member("machines-full-target", makerspace)
    machine = make_machine(makerspace)
    assert assign_operator(
        authenticated_client(manager), machine, full_operator, "full"
    ).status_code == 201
    full_client = authenticated_client(full_operator)

    full_denied = assign_operator(full_client, machine, target, "full")
    operate_allowed = assign_operator(full_client, machine, target, "operate")
    retired = full_client.post(
        reverse("admin-machine-retire", kwargs={"pk": machine.id}),
        {},
        format="json",
    )

    assert full_denied.status_code == 403
    assert operate_allowed.status_code == 201
    assert retired.status_code == 200
    assert retired.data["is_active"] is False
    assert retired.data["status"] == "offline"


def test_assigning_non_member_as_operator_returns_400():
    makerspace = enable_machines(make_space("machines-nonmember"))
    manager = make_member("machines-nonmember-manager", makerspace)
    outsider = make_user(
        "machines-nonmember-outsider",
        access_status=User.AccessStatus.ACTIVE,
    )
    machine = make_machine(makerspace)

    response = assign_operator(
        authenticated_client(manager), machine, outsider, "operate"
    )

    assert response.status_code == 400


def test_machine_types_custom_create_scope_permissions_and_global_uniqueness():
    makerspace = enable_machines(make_space("machines-types"))
    manager = make_member("machines-types-manager", makerspace)
    operator = make_handout_member("machines-types-operator", makerspace)
    machine = make_machine(makerspace)
    manager_client = authenticated_client(manager)
    assert assign_operator(manager_client, machine, operator, "operate").status_code == 201
    url = reverse("admin-machine-types", kwargs={"makerspace_id": makerspace.id})

    created = manager_client.post(
        url,
        {
            "slug": "plasma_cutter",
            "name": "Plasma Cutter",
            "icon": "spark",
            "capability_config": {"metering_unit": "minutes", "requires_booking": False},
            "managing_action": "manage_printing",
        },
        format="json",
    )
    denied = authenticated_client(operator).post(
        url,
        {"slug": "kiln", "name": "Kiln", "capability_config": {"metering_unit": "count", "requires_booking": False}},
        format="json",
    )
    listed = manager_client.get(url)

    assert created.status_code == 201
    assert created.data["managing_action"] == ""
    assert MachineType.objects.get(pk=created.data["id"]).managing_action == ""
    assert denied.status_code == 403
    assert listed.status_code == 200
    listed_ids = {row["id"] for row in response_rows(listed)}
    assert global_machine_type().id in listed_ids
    assert created.data["id"] in listed_ids

    with pytest.raises(IntegrityError), transaction.atomic():
        MachineType.objects.create(
            makerspace=None,
            slug="3d_printer",
            name="Duplicate Printer",
            is_builtin=True,
        )


def test_custom_machine_type_can_be_renamed_without_changing_server_fields():
    makerspace = enable_machines(make_space('machines-type-rename'))
    manager = make_member('machines-type-rename-manager', makerspace)
    machine_type = MachineType.objects.create(
        makerspace=makerspace,
        slug='laser-cutter',
        name='Laser Cutter',
        icon='laser',
        managing_action='',
    )
    url = reverse(
        'admin-machine-type-detail',
        kwargs={'makerspace_id': makerspace.id, 'pk': machine_type.id},
    )

    response = authenticated_client(manager).patch(
        url,
        {
            'name': 'Large Laser Cutter',
            'icon': 'spark',
            'slug': 'changed-slug',
            'managing_action': 'manage_printing',
        },
        format='json',
    )

    assert response.status_code == 200
    machine_type.refresh_from_db()
    assert machine_type.name == 'Large Laser Cutter'
    assert machine_type.icon == 'spark'
    assert machine_type.slug == 'laser-cutter'
    assert machine_type.managing_action == ''
    assert machine_type.makerspace == makerspace
    assert machine_type.is_builtin is False
    assert AuditLog.objects.filter(
        action='machine_type.updated',
        makerspace=makerspace,
        target_id=str(machine_type.id),
    ).exists()


def test_builtin_machine_type_rename_is_rejected():
    makerspace = enable_machines(make_space('machines-type-builtin'))
    manager = make_member('machines-type-builtin-manager', makerspace)
    machine_type = global_machine_type()

    response = authenticated_client(manager).patch(
        reverse(
            'admin-machine-type-detail',
            kwargs={'makerspace_id': makerspace.id, 'pk': machine_type.id},
        ),
        {'name': 'Renamed Printer'},
        format='json',
    )

    assert response.status_code == 400
    machine_type.refresh_from_db()
    assert machine_type.name != 'Renamed Printer'


def test_machine_type_rename_is_404_across_tenants():
    makerspace_a = enable_machines(make_space('machines-type-tenant-a'))
    makerspace_b = enable_machines(make_space('machines-type-tenant-b'))
    manager_a = make_member('machines-type-tenant-manager', makerspace_a)
    machine_type_b = MachineType.objects.create(
        makerspace=makerspace_b,
        slug='tenant-b-kiln',
        name='Tenant B Kiln',
    )

    response = authenticated_client(manager_a).patch(
        reverse(
            'admin-machine-type-detail',
            kwargs={'makerspace_id': makerspace_a.id, 'pk': machine_type_b.id},
        ),
        {'name': 'Leaked rename'},
        format='json',
    )

    assert response.status_code == 404


def test_machine_type_rename_requires_manage_machines_before_validation():
    makerspace = enable_machines(make_space('machines-type-forbidden'))
    actor = make_handout_member('machines-type-forbidden-actor', makerspace)

    response = authenticated_client(actor).patch(
        reverse(
            'admin-machine-type-detail',
            kwargs={'makerspace_id': makerspace.id, 'pk': global_machine_type().id},
        ),
        {'name': ''},
        format='json',
    )

    assert response.status_code == 403


def test_machine_type_rename_name_collision_returns_400():
    makerspace = enable_machines(make_space('machines-type-collision'))
    manager = make_member('machines-type-collision-manager', makerspace)
    MachineType.objects.create(
        makerspace=makerspace,
        slug='cnc-router',
        name='CNC Router',
    )
    machine_type = MachineType.objects.create(
        makerspace=makerspace,
        slug='workshop-kiln',
        name='Workshop Kiln',
    )

    response = authenticated_client(manager).patch(
        reverse(
            'admin-machine-type-detail',
            kwargs={'makerspace_id': makerspace.id, 'pk': machine_type.id},
        ),
        {'name': 'cnc router'},
        format='json',
    )

    assert response.status_code == 400
    machine_type.refresh_from_db()
    assert machine_type.name == 'Workshop Kiln'


def test_set_status_validates_status_and_writes_audit_log():
    makerspace = enable_machines(make_space("machines-status"))
    manager = make_member("machines-status-manager", makerspace)
    machine = make_machine(makerspace)
    client = authenticated_client(manager)
    url = reverse("admin-machine-set-status", kwargs={"pk": machine.id})

    valid = client.post(url, {"status": "maintenance"}, format="json")
    invalid = client.post(url, {"status": "broken"}, format="json")

    assert valid.status_code == 200
    assert valid.data["status"] == "maintenance"
    assert AuditLog.objects.filter(
        action="machine.status_changed",
        makerspace=makerspace,
    ).exists()
    assert invalid.status_code == 400


def test_usage_ledger_lists_entries_sums_detail_and_rejects_invalid_or_retired():
    makerspace = enable_machines(make_space("machines-usage"))
    manager = make_member("machines-usage-manager", makerspace)
    machine = make_machine(makerspace)
    client = authenticated_client(manager)
    usage_url = reverse("admin-machine-usage", kwargs={"pk": machine.id})

    first = client.post(
        usage_url,
        {"hours": "1.25", "note": "First job"},
        format="json",
    )
    second = client.post(
        usage_url,
        {"hours": "2.50", "note": "Second job"},
        format="json",
    )
    listed = client.get(usage_url)
    detail = client.get(reverse("admin-machine-detail", kwargs={"pk": machine.id}))
    invalid = client.post(usage_url, {"hours": "0"}, format="json")
    assert client.post(
        reverse("admin-machine-retire", kwargs={"pk": machine.id}),
        {},
        format="json",
    ).status_code == 200
    retired = client.post(usage_url, {"hours": "1.00"}, format="json")

    assert first.status_code == 201
    assert second.status_code == 201
    assert listed.status_code == 200
    assert len(response_rows(listed)) == 2
    assert Decimal(str(detail.data["usage_hours"])) == Decimal("3.75")
    assert invalid.status_code == 400
    assert retired.status_code == 400


def test_retired_machine_is_offline_rejects_mutations_and_has_no_delete_route():
    makerspace = enable_machines(make_space("machines-retire"))
    manager = make_member("machines-retire-manager", makerspace)
    machine = make_machine(makerspace)
    client = authenticated_client(manager)

    retired = client.post(
        reverse("admin-machine-retire", kwargs={"pk": machine.id}),
        {},
        format="json",
    )
    detail_url = reverse("admin-machine-detail", kwargs={"pk": machine.id})
    detail = client.get(detail_url)
    usage = client.post(
        reverse("admin-machine-usage", kwargs={"pk": machine.id}),
        {"hours": "1.00"},
        format="json",
    )
    error = client.post(
        reverse("admin-machine-error-logs", kwargs={"pk": machine.id}),
        {"severity": "error", "message": "Retired fault"},
        format="json",
    )
    status_response = client.post(
        reverse("admin-machine-set-status", kwargs={"pk": machine.id}),
        {"status": "idle"},
        format="json",
    )
    deleted = client.delete(detail_url)

    assert retired.status_code == 200
    assert detail.status_code == 200
    assert detail.data["is_active"] is False
    assert detail.data["status"] == "offline"
    assert usage.status_code == 400
    assert error.status_code == 400
    assert status_response.status_code == 400
    assert deleted.status_code == 405


def test_only_machine_admin_or_type_manager_can_unretire():
    makerspace = enable_machines(make_space("machines-unretire"))
    manager = make_member("machines-unretire-manager", makerspace)
    full_operator = make_handout_member("machines-unretire-full", makerspace)
    machine = make_machine(makerspace)
    manager_client = authenticated_client(manager)
    assert assign_operator(manager_client, machine, full_operator, "full").status_code == 201
    assert manager_client.post(
        reverse("admin-machine-retire", kwargs={"pk": machine.id}),
        {},
        format="json",
    ).status_code == 200
    url = reverse("admin-machine-unretire", kwargs={"pk": machine.id})

    denied = authenticated_client(full_operator).post(url, {}, format="json")
    allowed = manager_client.post(url, {}, format="json")

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.data["is_active"] is True

def test_machine_documents_presign_finalize_list_url_delete_and_reuse_guard():
    makerspace = enable_machines(make_space("machines-documents"))
    manager = make_member("machines-documents-manager", makerspace)
    machine = make_machine(makerspace)
    client = authenticated_client(manager)

    presign = client.post(
        reverse("admin-machine-document-presign", kwargs={"pk": machine.id}),
        {"filename": "manual.pdf", "content_type": "application/pdf"},
        format="json",
    )
    object_key = presign.data["object_key"]
    documents_url = reverse("admin-machine-documents", kwargs={"pk": machine.id})
    finalized = client.post(
        documents_url,
        {
            "object_key": object_key,
            "doc_type": "manual",
            "original_filename": "manual.pdf",
        },
        format="json",
    )
    document = MachineDocument.objects.get(pk=finalized.data["id"])
    listed = client.get(documents_url)
    signed = client.get(
        reverse("admin-machine-document-url", kwargs={"pk": document.id})
    )
    duplicate = client.post(
        documents_url,
        {
            "object_key": object_key,
            "doc_type": "sop",
            "original_filename": "reused.pdf",
        },
        format="json",
    )
    deleted = client.delete(
        reverse("admin-machine-document-detail", kwargs={"pk": document.id})
    )

    assert presign.status_code == 201
    assert object_key == f"machines/{makerspace.id}/x.pdf"
    assert presign.data["upload"] == {"url": "http://x", "fields": {}}
    assert finalized.status_code == 201
    assert "object_key" not in finalized.data
    assert listed.status_code == 200
    assert len(response_rows(listed)) == 1
    assert all("object_key" not in row for row in response_rows(listed))
    assert signed.status_code == 200
    assert signed.data == {"url": "http://signed"}
    assert duplicate.status_code == 400
    assert deleted.status_code == 204
    assert not MachineDocument.objects.filter(pk=document.pk).exists()


def test_machine_error_logs_create_list_and_validate_severity():
    makerspace = enable_machines(make_space("machines-errors"))
    manager = make_member("machines-errors-manager", makerspace)
    machine = make_machine(makerspace)
    client = authenticated_client(manager)
    url = reverse("admin-machine-error-logs", kwargs={"pk": machine.id})

    created = client.post(
        url,
        {"severity": "critical", "message": "Emergency stop triggered"},
        format="json",
    )
    listed = client.get(url)
    invalid = client.post(
        url,
        {"severity": "catastrophic", "message": "Unknown level"},
        format="json",
    )

    assert created.status_code == 201
    assert created.data["severity"] == "critical"
    assert listed.status_code == 200
    assert len(response_rows(listed)) == 1
    assert response_rows(listed)[0]["message"] == "Emergency stop triggered"
    assert invalid.status_code == 400

def test_machine_has_no_legacy_printer_bridge():
    assert not hasattr(Machine, "linked_print_printer")
    with pytest.raises(ModuleNotFoundError):
        __import__("apps.machines.signals")
    with pytest.raises(ModuleNotFoundError):
        __import__("apps.machines.linking")

def test_machines_module_gate_returns_400_when_disabled():
    makerspace = enable_machines(make_space("machines-module-gate"))
    manager = make_member("machines-module-manager", makerspace)
    makerspace.enabled_modules = [
        module for module in makerspace.enabled_modules if module != "machines"
    ]
    makerspace.save(update_fields=["enabled_modules"])

    response = authenticated_client(manager).get(
        reverse("admin-machines", kwargs={"makerspace_id": makerspace.id})
    )

    assert response.status_code == 400


def test_operator_only_list_is_scoped_to_assigned_machines():
    makerspace = enable_machines(make_space("machines-operator-scope"))
    manager = make_member("machines-scope-manager", makerspace)
    operator = make_handout_member("machines-scope-operator", makerspace)
    assigned_machine = make_machine(makerspace, name="Assigned Machine")
    make_machine(makerspace, name="Unassigned Machine")
    assert assign_operator(
        authenticated_client(manager), assigned_machine, operator, "operate"
    ).status_code == 201

    response = authenticated_client(operator).get(
        reverse("admin-machines", kwargs={"makerspace_id": makerspace.id})
    )

    assert response.status_code == 200
    assert [row["id"] for row in response_rows(response)] == [assigned_machine.id]

def test_machine_type_is_immutable_on_patch():
    # Stage-4 P1: a type manager must not be able to move a machine to another type
    # (which could retain control over a type they cannot manage). machine_type is
    # frozen after creation.
    makerspace = enable_machines(make_space("machines-type-immutable"))
    manager = make_member("machines-type-immutable-mgr", makerspace)
    machine = make_machine(makerspace, machine_type=global_machine_type())
    laser = global_machine_type("laser_cutter")

    response = authenticated_client(manager).patch(
        reverse("admin-machine-detail", kwargs={"pk": machine.id}),
        {"machine_type_id": laser.id, "name": "Renamed"},
        format="json",
    )

    assert response.status_code == 200
    machine.refresh_from_db()
    assert machine.machine_type == global_machine_type()  # unchanged
    assert machine.name == "Renamed"  # other fields still editable
    # Stage-4 P2: the PATCH response must carry request context so capability flags
    # reflect the actor (a manager can edit), matching the GET response.
    assert response.data["can_edit"] is True


def test_publicity_toggle_requires_manage_machines_and_returns_public_preview():
    makerspace = enable_machines(make_space('machines-publicity'))
    manager = make_member('machines-publicity-manager', makerspace)
    machine = make_machine(makerspace)
    MachineUsageEntry.objects.create(machine=machine, hours=Decimal('3.25'))

    response = authenticated_client(manager).patch(
        reverse('admin-machine-publicity', kwargs={'pk': machine.pk}),
        {'is_public': True},
        format='json',
    )

    machine.refresh_from_db()
    assert response.status_code == 200
    assert machine.is_public is True
    assert set(response.data) == {
        'name',
        'machine_type',
        'image_url',
        'status',
        'usage_hours',
    }
    assert set(response.data['machine_type']) == {'name', 'icon'}
    assert Decimal(response.data['usage_hours']) == Decimal('3.25')
    audit = AuditLog.objects.get(action='machine.publicity_changed')
    assert audit.actor == manager
    assert audit.makerspace == makerspace
    assert audit.meta == {'from': False, 'to': True}


def test_full_operator_cannot_publish_and_normal_patch_cannot_change_publicity():
    makerspace = enable_machines(make_space('machines-publicity-operator'))
    operator = make_handout_member('machines-publicity-full-operator', makerspace)
    machine = make_machine(makerspace)
    MachineOperator.objects.create(
        machine=machine,
        user=operator,
        access_level=MachineOperator.AccessLevel.FULL,
    )
    client = authenticated_client(operator)

    normal_patch = client.patch(
        reverse('admin-machine-detail', kwargs={'pk': machine.pk}),
        {'is_public': True, 'name': 'Operator-renamed machine'},
        format='json',
    )
    publicity = client.patch(
        reverse('admin-machine-publicity', kwargs={'pk': machine.pk}),
        {'is_public': True},
        format='json',
    )

    machine.refresh_from_db()
    assert normal_patch.status_code == 200
    assert machine.name == 'Operator-renamed machine'
    assert machine.is_public is False
    assert normal_patch.data['is_public'] is False
    assert publicity.status_code == 403
    assert not AuditLog.objects.filter(action='machine.publicity_changed').exists()


def test_publicity_scope_permission_and_module_checks_are_ordered():
    own = enable_machines(make_space('machines-publicity-scope-own'))
    other = enable_machines(make_space('machines-publicity-scope-other'))
    manager = make_member('machines-publicity-scope-manager', own)
    full_operator = make_handout_member('machines-publicity-scope-operator', own)
    own_machine = make_machine(own)
    foreign_machine = make_machine(other)
    MachineOperator.objects.create(
        machine=own_machine,
        user=full_operator,
        access_level=MachineOperator.AccessLevel.FULL,
    )
    own.enabled_modules = [name for name in own.enabled_modules if name != 'machines']
    own.save(update_fields=['enabled_modules'])

    manager_module = authenticated_client(manager).patch(
        reverse('admin-machine-publicity', kwargs={'pk': own_machine.pk}),
        {'is_public': True},
        format='json',
    )
    operator_permission = authenticated_client(full_operator).patch(
        reverse('admin-machine-publicity', kwargs={'pk': own_machine.pk}),
        {'is_public': True},
        format='json',
    )
    foreign_scope = authenticated_client(manager).patch(
        reverse('admin-machine-publicity', kwargs={'pk': foreign_machine.pk}),
        {'is_public': True},
        format='json',
    )

    assert manager_module.status_code == 400
    assert operator_permission.status_code == 403
    assert foreign_scope.status_code == 404


def test_remove_operator_rejected_on_retired_machine():
    makerspace = enable_machines(make_space("machines-remove-retired"))
    manager = make_member("machines-remove-retired-mgr", makerspace)
    operator = make_member(
        "machines-remove-retired-op",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.SPACE_MANAGER,
    )
    machine = make_machine(makerspace)
    client = authenticated_client(manager)
    assert assign_operator(client, machine, operator, "operate").status_code == 201
    assert client.post(
        reverse("admin-machine-retire", kwargs={"pk": machine.id}), {}, format="json"
    ).status_code == 200

    removed = client.delete(
        reverse(
            "admin-machine-operator-detail",
            kwargs={"pk": machine.id, "user_pk": operator.id},
        )
    )
    assert removed.status_code == 400  # retired machines reject operator mutations


def test_duplicate_custom_type_slug_returns_400_not_500():
    makerspace = enable_machines(make_space("machines-dup-slug"))
    manager = make_member("machines-dup-slug-mgr", makerspace)
    client = authenticated_client(manager)
    url = reverse("admin-machine-types", kwargs={"makerspace_id": makerspace.id})
    payload = {"slug": "resin-tank", "name": "Resin Tank", "icon": "", "capability_config": {"metering_unit": "volume", "requires_booking": False}}

    assert client.post(url, payload, format="json").status_code == 201
    duplicate = client.post(url, payload, format="json")
    assert duplicate.status_code == 400


def test_machine_serializer_exposes_can_manage_capability():
    makerspace = enable_machines(make_space("machines-can-manage"))
    manager = make_member("machines-can-manage-mgr", makerspace)
    machine = make_machine(makerspace)

    response = authenticated_client(manager).get(
        reverse("admin-machine-detail", kwargs={"pk": machine.id})
    )
    assert response.status_code == 200
    assert response.data["can_manage"] is True


def test_machine_serializer_exposes_only_lightweight_warranty_status():
    makerspace = enable_machines(make_space("machines-warranty-status"))
    manager = make_member("machines-warranty-status-manager", makerspace)
    machine = make_machine(makerspace)
    client = authenticated_client(manager)
    url = reverse("admin-machine-detail", kwargs={"pk": machine.id})

    uncovered = client.get(url)
    Warranty.objects.create(
        makerspace=makerspace,
        machine=machine,
        warranty_expires_on=timezone.localdate(),
        vendor_name="PRIVATE_MACHINE_VENDOR",
        vendor_contact="PRIVATE_MACHINE_CONTACT",
    )
    covered = client.get(url)

    assert uncovered.status_code == 200
    assert uncovered.data["warranty_status"] == "unknown"
    assert covered.status_code == 200
    assert covered.data["warranty_status"] == "expiring_soon"
    for field in (
        "warranty",
        "vendor_name",
        "vendor_contact",
        "purchased_on",
        "warranty_expires_on",
    ):
        assert field not in covered.data


def test_machine_image_presign_finalize_delete_and_audit(monkeypatch, settings):
    settings.PUBLIC_IMAGE_BASE_URL = "http://cdn.test/public-images"
    delete_object = mock_machine_image_storage(monkeypatch)
    makerspace = enable_machines(make_space("machines-image-flow"))
    manager = make_member("machines-image-flow-manager", makerspace)
    machine = make_machine(makerspace)
    client = authenticated_client(manager)
    url = machine_image_url(machine)

    presigned = client.post(
        url,
        {"content_type": "image/png", "filename": "machine.png"},
        format="json",
    )
    object_key = presigned.data["object_key"]
    finalized = client.put(url, {"object_key": object_key}, format="json")

    assert presigned.status_code == 201
    assert object_key.startswith(f"machine/{makerspace.id}/")
    assert finalized.status_code == 200
    assert "image_key" not in finalized.data
    assert finalized.data["image_url"] == f"http://cdn.test/public-images/{object_key}"
    machine.refresh_from_db()
    assert machine.image_key == object_key
    assert AuditLog.objects.filter(action="machine.image_updated").exists()

    removed = client.delete(url)

    assert removed.status_code == 200
    assert "image_key" not in removed.data
    assert removed.data["image_url"] is None
    machine.refresh_from_db()
    assert machine.image_key == ""
    delete_object.assert_called_once_with(object_key)
    assert AuditLog.objects.filter(action="machine.image_removed").exists()


def test_machine_image_rejects_invalid_mime_without_calling_storage(monkeypatch):
    makerspace = enable_machines(make_space("machines-image-mime"))
    manager = make_member("machines-image-mime-manager", makerspace)
    machine = make_machine(makerspace)
    presign = Mock(side_effect=AssertionError("storage should not be called"))
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.presigned_upload",
        presign,
    )

    response = authenticated_client(manager).post(
        machine_image_url(machine),
        {"content_type": "image/svg+xml", "filename": "machine.svg"},
        format="json",
    )

    assert response.status_code == 400
    presign.assert_not_called()
    assert AuditLog.objects.count() == 0


def test_machine_image_rejects_foreign_key_prefix(monkeypatch):
    mock_machine_image_storage(monkeypatch)
    makerspace = enable_machines(make_space("machines-image-prefix"))
    manager = make_member("machines-image-prefix-manager", makerspace)
    machine = make_machine(makerspace)

    response = authenticated_client(manager).put(
        machine_image_url(machine),
        {"object_key": "machine/999/not-yours.png"},
        format="json",
    )

    assert response.status_code == 400
    machine.refresh_from_db()
    assert machine.image_key == ""


def test_machine_image_rejects_key_reused_by_another_model(monkeypatch):
    mock_machine_image_storage(monkeypatch)
    makerspace = enable_machines(make_space("machines-image-reuse"))
    manager = make_member("machines-image-reuse-manager", makerspace)
    machine = make_machine(makerspace)
    object_key = f"machine/{makerspace.id}/shared.png"
    InventoryProduct.objects.create(
        makerspace=makerspace,
        name="Image key owner",
        image_key=object_key,
    )

    response = authenticated_client(manager).put(
        machine_image_url(machine),
        {"object_key": object_key},
        format="json",
    )

    assert response.status_code == 400
    machine.refresh_from_db()
    assert machine.image_key == ""


def test_machine_image_storage_unavailable_returns_503(monkeypatch):
    makerspace = enable_machines(make_space("machines-image-storage"))
    manager = make_member("machines-image-storage-manager", makerspace)
    machine = make_machine(makerspace)

    def unavailable(*args, **kwargs):
        raise StorageUnavailable()

    monkeypatch.setattr(
        "apps.inventory.public_image_storage.presigned_upload",
        unavailable,
    )
    response = authenticated_client(manager).post(
        machine_image_url(machine),
        {"content_type": "image/jpeg", "filename": "machine.jpg"},
        format="json",
    )

    assert response.status_code == 503
    assert AuditLog.objects.count() == 0


def test_makerspace_purge_collection_includes_machine_image():
    makerspace = enable_machines(make_space("machines-image-purge"))
    machine = make_machine(makerspace)
    machine.image_key = f"machine/{makerspace.id}/purge.png"
    machine.save(update_fields=["image_key"])

    keys = makerspace_lifecycle._collect_public_image_keys(makerspace)

    assert machine.image_key in keys


def test_operate_only_operator_cannot_manage_machine_image(monkeypatch):
    mock_machine_image_storage(monkeypatch)
    makerspace = enable_machines(make_space("machines-image-operator"))
    operator = make_handout_member("machines-image-operator-user", makerspace)
    machine = make_machine(makerspace)
    MachineOperator.objects.create(
        machine=machine,
        user=operator,
        access_level=MachineOperator.AccessLevel.OPERATE,
    )

    response = authenticated_client(operator).post(
        machine_image_url(machine),
        {"content_type": "image/png", "filename": "machine.png"},
        format="json",
    )

    assert response.status_code == 403


def test_machine_image_is_404_across_tenants(monkeypatch):
    mock_machine_image_storage(monkeypatch)
    own_space = enable_machines(make_space("machines-image-own"))
    other_space = enable_machines(make_space("machines-image-other"))
    manager = make_member("machines-image-own-manager", own_space)
    other_machine = make_machine(other_space)

    response = authenticated_client(manager).post(
        machine_image_url(other_machine),
        {"content_type": "image/png", "filename": "machine.png"},
        format="json",
    )

    assert response.status_code == 404


def _consumables_url(machine):
    return reverse("admin-machine-consumables", kwargs={"pk": machine.pk})


def _consumable_url(machine, consumable_id):
    return reverse(
        "admin-machine-consumable-detail",
        kwargs={"pk": machine.pk, "cid": consumable_id},
    )


def _consumption_url(machine, consumable_id):
    return reverse(
        "admin-machine-consumption-log",
        kwargs={"pk": machine.pk, "cid": consumable_id},
    )


def _consumable_product(makerspace, name, available=10, **overrides):
    return InventoryProduct.objects.create(
        makerspace=makerspace,
        name=name,
        total_quantity=available,
        available_quantity=available,
        **overrides,
    )


def _operate_only_user(makerspace, machine, username):
    user = make_handout_member(username, makerspace)
    MachineOperator.objects.create(
        machine=machine,
        user=user,
        access_level=MachineOperator.AccessLevel.OPERATE,
    )
    return user


def test_machine_consumables_link_count_and_grams_with_live_balances():
    makerspace = enable_machines(make_space("machine-consumables-link"))
    manager = make_member("machine-consumables-link-manager", makerspace)
    machine = make_machine(makerspace)
    product = _consumable_product(makerspace, "Coolant bottles", 8)
    client = authenticated_client(manager)

    count = client.post(
        _consumables_url(machine),
        {
            "measurement": "count",
            "product_id": product.pk,
            "low_threshold": "2.00",
            "note": "Cabinet stock",
        },
        format="json",
    )
    grams = client.post(
        _consumables_url(machine),
        {
            "measurement": "grams",
            "label": "Cutting compound",
            "remaining": "750.50",
            "low_threshold": "100.00",
        },
        format="json",
    )

    assert count.status_code == 201
    assert count.data["product_name"] == product.name
    assert count.data["available"] == 8
    assert count.data["remaining"] is None
    assert grams.status_code == 201
    assert grams.data["product"] is None
    assert grams.data["available"] is None
    assert Decimal(grams.data["remaining"]) == Decimal("750.50")
    assert MachineConsumable.objects.filter(machine=machine).count() == 2
    assert AuditLog.objects.filter(action="machine.consumable_linked").count() == 2


def test_count_consumable_rejects_cross_makerspace_and_individual_products():
    makerspace = enable_machines(make_space("machine-consumables-product-scope"))
    other = enable_machines(make_space("machine-consumables-product-other"))
    manager = make_member("machine-consumables-product-manager", makerspace)
    machine = make_machine(makerspace)
    foreign = _consumable_product(other, "Foreign product", 3)
    individual = _consumable_product(
        makerspace,
        "Serialized product",
        1,
        tracking_mode=TrackingMode.INDIVIDUAL,
    )
    client = authenticated_client(manager)

    cross_response = client.post(
        _consumables_url(machine),
        {"measurement": "count", "product_id": foreign.pk},
        format="json",
    )
    individual_response = client.post(
        _consumables_url(machine),
        {"measurement": "count", "product_id": individual.pk},
        format="json",
    )

    assert cross_response.status_code == 400
    assert individual_response.status_code == 400
    assert MachineConsumable.objects.count() == 0


def test_consumable_link_and_unlink_require_manage_but_log_allows_operate():
    makerspace = enable_machines(make_space("machine-consumables-permissions"))
    manager = make_member("machine-consumables-permissions-manager", makerspace)
    machine = make_machine(makerspace)
    operator = _operate_only_user(
        makerspace, machine, "machine-consumables-permissions-operator"
    )
    product = _consumable_product(makerspace, "Abrasive discs", 6)
    operator_client = authenticated_client(operator)

    forbidden_link = operator_client.post(
        _consumables_url(machine),
        {"measurement": "count", "product_id": product.pk},
        format="json",
    )
    linked = authenticated_client(manager).post(
        _consumables_url(machine),
        {"measurement": "count", "product_id": product.pk},
        format="json",
    )
    logged = operator_client.post(
        _consumption_url(machine, linked.data["id"]),
        {"quantity": "2"},
        format="json",
    )
    forbidden_unlink = operator_client.delete(
        _consumable_url(machine, linked.data["id"])
    )
    removed = authenticated_client(manager).delete(
        _consumable_url(machine, linked.data["id"])
    )

    assert forbidden_link.status_code == 403
    assert linked.status_code == 201
    assert logged.status_code == 200
    assert logged.data["available"] == 4
    assert forbidden_unlink.status_code == 403
    assert removed.status_code == 204
    assert AuditLog.objects.filter(action="machine.consumable_unlinked").exists()


def test_consumption_rejects_retired_machine_and_foreign_consumable():
    makerspace = enable_machines(make_space("machine-consumables-retired"))
    manager = make_member("machine-consumables-retired-manager", makerspace)
    machine = make_machine(makerspace, name="Primary")
    other_machine = make_machine(makerspace, name="Other")
    client = authenticated_client(manager)
    linked = client.post(
        _consumables_url(machine),
        {"measurement": "grams", "label": "Grease", "remaining": "20"},
        format="json",
    )
    foreign = client.post(
        _consumables_url(other_machine),
        {"measurement": "grams", "label": "Oil", "remaining": "20"},
        format="json",
    )

    foreign_response = client.post(
        _consumption_url(machine, foreign.data["id"]),
        {"quantity": "1"},
        format="json",
    )
    machine.is_active = False
    machine.save(update_fields=["is_active"])
    retired_response = client.post(
        _consumption_url(machine, linked.data["id"]),
        {"quantity": "1"},
        format="json",
    )

    assert foreign_response.status_code == 400
    assert retired_response.status_code == 400
    assert "retired" in str(retired_response.data).lower()


def test_count_consumption_decrements_availability_and_overdraw_is_400():
    makerspace = enable_machines(make_space("machine-consumables-count-log"))
    manager = make_member("machine-consumables-count-manager", makerspace)
    machine = make_machine(makerspace)
    product = _consumable_product(makerspace, "Filter cartridges", 5)
    client = authenticated_client(manager)
    linked = client.post(
        _consumables_url(machine),
        {"measurement": "count", "product_id": product.pk},
        format="json",
    )

    oversized = client.post(
        _consumption_url(machine, linked.data["id"]),
        {"quantity": "6"},
        format="json",
    )
    consumed = client.post(
        _consumption_url(machine, linked.data["id"]),
        {"quantity": "3"},
        format="json",
    )
    competing_overdraw = client.post(
        _consumption_url(machine, linked.data["id"]),
        {"quantity": "3"},
        format="json",
    )

    product.refresh_from_db()
    assert oversized.status_code == 400
    assert consumed.status_code == 200
    assert competing_overdraw.status_code == 400
    assert product.available_quantity == 2
    assert InventoryAdjustment.objects.filter(
        product=product, delta_available=-3, delta_damaged=0, delta_lost=0
    ).exists()
    assert AuditLog.objects.filter(action="inventory.quantity_adjusted").exists()
    assert AuditLog.objects.filter(action="machine.consumption_logged").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_count_consumption_never_overdraws():
    makerspace = enable_machines(make_space("machine-consumables-concurrent"))
    manager = make_member("machine-consumables-concurrent-manager", makerspace)
    # This test is transaction=True, so pytest-django flushes migration-seeded data
    # (the global built-in MachineTypes); create an explicit type instead of relying
    # on global_machine_type(), which is absent after another transactional test.
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug="concurrent-type", name="Concurrent Type",
    )
    machine = make_machine(makerspace, machine_type=machine_type)
    product = _consumable_product(makerspace, "Concurrent stock", 5)
    linked = authenticated_client(manager).post(
        _consumables_url(machine),
        {"measurement": "count", "product_id": product.pk},
        format="json",
    )
    barrier = Barrier(2)

    def consume():
        close_old_connections()
        client = authenticated_client(manager)
        barrier.wait()
        response = client.post(
            _consumption_url(machine, linked.data["id"]),
            {"quantity": "4"},
            format="json",
        )
        close_old_connections()
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: consume(), range(2)))

    # adjust_quantities row-locks the product (select_for_update in an atomic block),
    # so the two consumptions are strictly serialized: one wins (5 -> 1), the other
    # would overdraw and is rejected with 400.
    product.refresh_from_db()
    assert sorted(statuses) == [200, 400]
    assert product.available_quantity == 1


def test_grams_consumption_decrements_locked_local_ledger_without_overdraw():
    makerspace = enable_machines(make_space("machine-consumables-grams-log"))
    manager = make_member("machine-consumables-grams-manager", makerspace)
    machine = make_machine(makerspace)
    client = authenticated_client(manager)
    linked = client.post(
        _consumables_url(machine),
        {"measurement": "grams", "label": "Polishing paste", "remaining": "12.50"},
        format="json",
    )

    consumed = client.post(
        _consumption_url(machine, linked.data["id"]),
        {"quantity": "2.25"},
        format="json",
    )
    overdraw = client.post(
        _consumption_url(machine, linked.data["id"]),
        {"quantity": "11"},
        format="json",
    )

    row = MachineConsumable.objects.get(pk=linked.data["id"])
    assert consumed.status_code == 200
    assert Decimal(consumed.data["remaining"]) == Decimal("10.25")
    assert overdraw.status_code == 400
    assert row.remaining == Decimal("10.25")
    assert InventoryAdjustment.objects.count() == 0


def test_consumables_respect_disabled_machines_module_after_permission_check():
    makerspace = enable_machines(make_space("machine-consumables-module"))
    manager = make_member("machine-consumables-module-manager", makerspace)
    machine = make_machine(makerspace)
    makerspace.enabled_modules = [
        name for name in makerspace.enabled_modules if name != "machines"
    ]
    makerspace.save(update_fields=["enabled_modules"])

    response = authenticated_client(manager).get(_consumables_url(machine))

    assert response.status_code == 400


def test_consumable_candidates_are_minimal_and_filter_archived_and_individual():
    makerspace = enable_machines(make_space("machine-consumables-candidates"))
    machine = make_machine(makerspace)
    operator = _operate_only_user(
        makerspace, machine, "machine-consumables-candidates-operator"
    )
    eligible = _consumable_product(makerspace, "Eligible", 7)
    _consumable_product(makerspace, "Archived", 3, is_archived=True)
    _consumable_product(
        makerspace,
        "Individual",
        1,
        tracking_mode=TrackingMode.INDIVIDUAL,
    )
    other = enable_machines(make_space("machine-consumables-candidates-other"))
    _consumable_product(other, "Foreign", 9)

    response = authenticated_client(operator).get(
        reverse("admin-machine-consumable-candidates", kwargs={"pk": machine.pk})
    )

    assert response.status_code == 200
    assert response.data == [
        {"id": eligible.pk, "name": eligible.name, "available": 7}
    ]
    assert set(response.data[0]) == {"id", "name", "available"}
