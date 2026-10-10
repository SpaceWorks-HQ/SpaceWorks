"""machines x procurement / features across uninstall (matrix M15, M5, N8, B6).

Receiving a printer through procurement created a `Machine` behind every gate the
machine registry has: it checked `printing` only, which does not require `machines`,
and skipped the managed machine quota. The pins below cover feature pruning across an
uninstall/reinstall and a booking whose space still names a machine type after
`machines` is gone.
"""

import pytest
from rest_framework.exceptions import PermissionDenied

from apps.bookings.models import Booking
from apps.machines import procurement as machine_procurement
from apps.machines.models import Machine
from apps.makerspaces.module_install import install_module, uninstall_module
from apps.makerspaces.platform import feature_enabled
from apps.procurement.models import ToBuyItem
from tests.machines import certification_helpers as cert
from tests.return_helpers import authenticated_client, make_member, make_space
from tests.test_procurement_move_to_inventory import move_printing_url, received_item

pytestmark = pytest.mark.django_db

PRINTER = {"target": "printer", "name": "Prusa MK4", "model": "MK4", "status": "active"}


def test_receiving_a_printer_needs_the_machines_module():
    space = make_space("combo-proc-printer-off")
    actor = make_member("combo-proc-printer-off-mgr", space)
    space.enabled_modules = [key for key in space.enabled_modules if key != "machines"]
    space.save(update_fields=["enabled_modules"])
    item = received_item(space, kind=ToBuyItem.Kind.PRINTING, name="Printer")

    response = authenticated_client(actor).post(move_printing_url(item), PRINTER, format="json")

    assert response.status_code == 400, response.data
    assert "machines is disabled" in str(response.data)
    assert not Machine.objects.filter(makerspace=space).exists()
    item.refresh_from_db()
    assert item.resulting_machine_id is None


def test_receiving_a_printer_is_charged_to_the_machine_quota(monkeypatch):
    space = make_space("combo-proc-printer-quota")
    actor = make_member("combo-proc-printer-quota-mgr", space)
    item = received_item(space, kind=ToBuyItem.Kind.PRINTING, name="Printer")
    calls = []
    monkeypatch.setattr(
        machine_procurement.limits, "check_quota",
        lambda makerspace, key, *, adding=1: calls.append((makerspace.pk, key, adding)),
    )

    response = authenticated_client(actor).post(move_printing_url(item), PRINTER, format="json")

    assert response.status_code == 200, response.data
    assert calls == [(space.pk, "machines", 1)]


@pytest.mark.parametrize(
    ("feature", "module"),
    [("machines.certifications", "machines"), ("notifications.delegated_recipients", "maintenance")],
)
def test_a_feature_is_pruned_with_its_module_and_stays_off_on_reinstall(feature, module):
    space = make_space(f"combo-prune-{feature.replace('.', '-')}")
    space.enabled_features = sorted({*space.enabled_features, feature})
    space.save(update_fields=["enabled_features"])
    assert feature_enabled(space, feature)

    uninstall_module(space, module)
    space.refresh_from_db()
    assert feature not in space.enabled_features
    install_module(space, module)
    space.refresh_from_db()

    assert feature not in space.enabled_features
    assert not feature_enabled(space, feature)


def test_a_space_keeping_its_machine_type_books_ungated_once_machines_is_gone():
    """B6: the feature reads its parent module at runtime and is pruned on uninstall."""
    space = cert._space("combo-booking-cert-machines-off")
    machine_type = cert._machine_type(space)
    cert._certification(space, machine_type)
    member, _ = cert._member(space, "combo-booking-cert-member")
    room = cert._bookable(space, machine_type)

    with pytest.raises(PermissionDenied):
        cert._book(room, member)

    uninstall_module(space, "machines")
    booking = cert._book(room, member)
    assert Booking.objects.filter(pk=booking.pk).exists()


def test_dashboard_print_tiles_follow_the_printing_module():
    """M11: with `printing` uninstalled the print tiles read zero, like maintenance does."""
    from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue

    space = make_space("combo-dashboard-prints")
    manager = make_member("combo-dashboard-prints-mgr", space)
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=printer_type, name="Prints")
    MachineServiceRequest.objects.create(
        makerspace=space, queue=queue, requester=manager, requester_name=manager.username,
        title="Queued print", status=MachineServiceRequest.Status.PENDING,
    )
    url = f"/api/v1/admin/makerspace/{space.pk}/dashboard"
    client = authenticated_client(manager)

    assert client.get(url).data["pending_prints"] == 1
    uninstall_module(space, "printing")
    response = client.get(url)

    assert response.status_code == 200
    assert response.data["pending_prints"] == 0
    assert response.data["active_prints"] == 0
