"""OFF-state contracts for machines and the services layered on them."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.inventory.models import InventoryProduct
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceQueue
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_profiles import RECOMMENDED, profile_modules
from tests.member_submission import active_member_client


pytestmark = pytest.mark.django_db

MACHINE_MODULES = ("machines", "machine_service", "printing", "maintenance")


def _space(slug, *, without=None):
    modules = set(profile_modules(RECOMMENDED))
    if without is not None:
        modules.discard(without)
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=sorted(modules),
        public_inventory_enabled=True,
    )


def _enable(space, module_key):
    space.enabled_modules = sorted({*(space.enabled_modules or []), module_key})
    space.save(update_fields=["enabled_modules"])


def _account(username, *, superadmin=False):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        display_name="Machine Module User",
        role=User.Role.SUPERADMIN if superadmin else User.Role.REQUESTER,
        is_staff=superadmin,
        is_superuser=superadmin,
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def _machine(space, suffix="machine", *, public=True):
    machine_type = MachineType.objects.create(
        makerspace=space,
        slug=f"{space.slug}-{suffix}",
        name="General machine",
    )
    return Machine.objects.create(
        makerspace=space,
        machine_type=machine_type,
        name="Bench machine",
        is_public=public,
    )


def _printer_queue(space):
    printer_type, _ = MachineType.objects.get_or_create(
        makerspace=None,
        slug="3d_printer",
        defaults={
            "name": "3D Printer",
            "is_builtin": True,
            "capability_config": PRINTER_CONFIG,
        },
    )
    return ServiceQueue.objects.create(
        makerspace=space,
        machine_type=printer_type,
        name=f"{space.slug} public prints",
    )


def _run_loan_spine(module_key):
    """Browse -> propose -> queue -> accept -> status with one assigned key OFF."""
    label = module_key.replace("_", "-")
    space = _space(f"machines-off-{label}", without=module_key)
    assert module_key not in space.enabled_modules
    product = InventoryProduct.objects.create(
        makerspace=space,
        name="Torque wrench",
        total_quantity=3,
        available_quantity=3,
        is_public=True,
    )

    catalog = _client().get(
        reverse("inventory:public-inventory", args=[space.slug])
    )
    assert catalog.status_code == 200, catalog.data

    requester = _account(f"machines-off-{label}-requester")
    submitted = _client(requester).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {
            "requested_for": "Module independence check",
            "items": [{"product_id": product.pk, "quantity": 1}],
        },
        format="json",
    )
    assert submitted.status_code == 201, submitted.data

    staff = _client(_account(f"machines-off-{label}-staff", superadmin=True))
    pending = staff.get(
        reverse("hardware_requests:pending-requests", args=[space.pk])
    )
    assert pending.status_code == 200, pending.data
    assert pending.data["count"] == 1

    accepted = staff.post(
        reverse(
            "hardware_requests:request-accept",
            args=[pending.data["results"][0]["id"]],
        ),
        {},
        format="json",
    )
    assert accepted.status_code == 200, accepted.data
    assert accepted.data["status"] == "accepted"

    public_status = _client().get(
        reverse(
            "hardware_requests:request-status",
            args=[submitted.data["public_token"]],
        )
    )
    assert public_status.status_code == 200, public_status.data


@pytest.mark.parametrize("module_key", MACHINE_MODULES)
def test_each_machine_optional_module_off_leaves_the_complete_loan_spine_working(
    module_key,
):
    """Machine capabilities are optional and cannot become loan dependencies."""
    _run_loan_spine(module_key)


def test_machines_off_hides_the_public_catalogue_and_on_restores_it():
    space = _space("machines-gate", without="machines")
    _machine(space)
    url = reverse("public-machines", args=[space.slug])

    refused = _client().get(url)
    assert refused.status_code == 404

    _enable(space, "machines")
    enabled = _client().get(url)
    assert enabled.status_code == 200, enabled.data


def test_machine_service_off_refuses_submission_and_on_accepts_an_active_member():
    """The member row isolates the module gate from the separate presence policy."""
    space = _space("machine-service-gate", without="machine_service")
    _enable(space, "membership")
    machine = _machine(space)
    _, client = active_member_client(space, "machine-service-gate-member")
    url = reverse("public-machine-service-request-submit", args=[space.slug])
    payload = {"machine_id": machine.pk, "title": "Cut acrylic"}

    refused = client.post(url, payload, format="json")
    assert refused.status_code == 400
    assert "machine_service is disabled" in str(refused.data)

    _enable(space, "machine_service")
    enabled = client.post(url, payload, format="json")
    assert enabled.status_code == 201, enabled.data
    assert MachineServiceRequest.objects.filter(makerspace=space).count() == 1


def test_printing_off_refuses_the_public_queue_instead_of_leaking_the_surface():
    """RECOMMENDED enables the substrate, not the separately optional printer pack."""
    space = _space("printing-off-gate")
    assert "machine_service" in space.enabled_modules
    assert "printing" not in space.enabled_modules
    _printer_queue(space)

    refused = _client().get(
        reverse("public-printer-service-queues", args=[space.slug])
    )

    assert refused.status_code == 400
    assert "printing" in str(refused.data)


def test_printing_on_exposes_the_public_printer_queue():
    space = _space("printing-on-gate")
    _enable(space, "printing")
    queue = _printer_queue(space)

    enabled = _client().get(
        reverse("public-printer-service-queues", args=[space.slug])
    )

    assert enabled.status_code == 200, enabled.data
    assert [row["id"] for row in enabled.data] == [queue.pk]


def test_maintenance_off_refuses_logs_and_on_restores_them():
    space = _space("maintenance-gate")
    machine = _machine(space)
    client = _client(_account("maintenance-gate-staff", superadmin=True))
    url = reverse(
        "admin-maintenance-log-list-create",
        kwargs={"makerspace_id": space.pk, "machine_id": machine.pk},
    )

    refused = client.get(url)
    assert refused.status_code == 400
    assert "maintenance is disabled" in str(refused.data)

    _enable(space, "maintenance")
    enabled = client.get(url)
    assert enabled.status_code == 200, enabled.data


def test_recommended_machine_service_accepts_an_active_account_without_membership():
    """A default-installed public workflow must not be dead for every ordinary account."""
    space = _space("recommended-machine-service")
    assert "machine_service" in space.enabled_modules
    assert "membership" not in space.enabled_modules
    machine = _machine(space)

    response = _client(_account("recommended-machine-service-user")).post(
        reverse("public-machine-service-request-submit", args=[space.slug]),
        {"machine_id": machine.pk, "title": "Default profile job"},
        format="json",
    )

    assert response.status_code == 201, response.data


def test_recommended_printer_submit_refuses_as_printing_off_before_membership_is_considered():
    """An OFF module must report its own gate, not an unrelated identity requirement."""
    space = _space("recommended-printer-service")
    assert "machine_service" in space.enabled_modules
    assert "membership" not in space.enabled_modules
    assert "printing" not in space.enabled_modules
    queue = _printer_queue(space)

    response = _client(_account("recommended-printer-service-user")).post(
        reverse("public-printer-service-request", args=[space.slug]),
        {"queue_id": queue.pk, "title": "Default profile print"},
        format="json",
    )

    assert response.status_code == 400
    assert "printing" in str(response.data)
