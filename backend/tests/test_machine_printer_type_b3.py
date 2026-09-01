"""B3: the printer type config exercises the generic machine-service kernel."""

from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.machines import role_scope
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceQueue
from apps.machines.serializers import MachineSerializer
from apps.machines.service_consumable_pools import create_pool, log_typed_manual_usage
from apps.machines.service_errors import ServiceMachineUnavailable
from apps.machines.service_file_policies import policy_for_queue
from apps.machines.service_reports import build_printer_service_report
from apps.machines.service_workflow import accept, collect, complete, start, submit
from apps.operations.report_registry import report_definition
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def printer(space, *, name="Printer", model="MK4"):
    machine_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    return Machine.objects.create(
        makerspace=space, machine_type=machine_type, name=name,
        type_payload={"model": model},
    )


def test_printer_type_contract_drives_full_generic_lifecycle():
    space = make_space("b3-printer-lifecycle")
    actor, requester = make_user("b3-printer-operator"), make_user("b3-printer-requester")
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    assert printer_type.capability_config["schema"] == "3d-printer-v1"
    assert printer_type.capability_config["pooled_service_queue"] is True

    target = printer(space)
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=printer_type, name="Print queue")
    assert policy_for_queue(queue).name == "printer"
    pool = create_pool(space, actor, machine=target, material="PLA", color="Blue", initial_grams="100")
    request = submit(
        queue, requester, actor=actor, requester_name="Requester", contact_email="r@example.test",
        contact_phone="1", title="Bracket", capability_payload={
            "requested_material": "PLA", "requested_color": "Blue", "quantity": 1,
            "estimated_grams": "20",
        },
    )
    assert request.assigned_machine_id is None
    accept(request, actor, estimated_minutes=30)
    started = start(request, actor, role_scope.EXEMPT, machine_id=target.id, consumable_pool_id=pool.id, planned_grams="20")
    assert started.run_machine_model == "MK4"
    assert (started.run_consumable_material, started.run_consumable_color) == ("PLA", "Blue")
    complete(started, actor, actual_minutes=25, consumptions=[], actual_grams="12")
    collected = collect(started, actor)
    pool.refresh_from_db()
    # C.3: collect() no longer marks the legacy payment_status; the Payment model is the authority.
    assert (collected.payment_status, pool.remaining_grams) == ("none", Decimal("88.00"))

    usage = log_typed_manual_usage(
        target, actor, duration_minutes=60, outcome="failed", percent_complete=50,
        reason="Layer shift", grams="5", pool=pool,
    )
    assert usage.hours == Decimal("0.50")
    rows = build_printer_service_report(space.id).records
    machine_row = next(row for row in rows if row["machine_id"] == target.id)
    assert machine_row["completed_hours"] == 0.42
    assert machine_row["manual_hours"] == 0.5
    assert report_definition("printer-service").builder_path == "apps.machines.service_reports.build_printer_service_report"


def test_printer_contract_rejects_invalid_model_pool_and_cross_tenant_or_type_allocation():
    space, other = make_space("b3-printer-contract"), make_space("b3-printer-other")
    actor, requester = make_user("b3-printer-contract-operator"), make_user("b3-printer-contract-requester")
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    serializer = MachineSerializer(data={
        "machine_type_id": printer_type.id, "name": "Missing model", "type_payload": {},
    })
    assert not serializer.is_valid()
    target = printer(space)
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=printer_type, name="Contract queue")
    with pytest.raises(ValidationError, match="material"):
        create_pool(space, actor, machine=target, material="ABS", color="Blue", initial_grams="10")

    request = submit(
        queue, requester, actor=actor, requester_name="Requester", contact_email="r@example.test",
        contact_phone="1", title="Bracket", capability_payload={
            "requested_material": "PLA", "requested_color": "Blue", "quantity": 1,
        },
    )
    accept(request, actor, estimated_minutes=10)
    foreign = printer(other, name="Foreign")
    other_type = MachineType.objects.create(makerspace=space, slug="b3-non-printer", name="Non printer")
    wrong = Machine.objects.create(makerspace=space, machine_type=other_type, name="Other")
    with pytest.raises(ServiceMachineUnavailable):
        start(request, actor, role_scope.EXEMPT, machine_id=foreign.id)
    with pytest.raises(ServiceMachineUnavailable):
        start(request, actor, role_scope.EXEMPT, machine_id=wrong.id)

    ordinary = Machine.objects.create(makerspace=space, machine_type=other_type, name="Legacy machine")
    legacy = submit(ordinary, requester, actor=actor, requester_name="Requester", contact_email="r@example.test", contact_phone="1", title="Repair")
    assert legacy.capability_payload == {} and legacy.assigned_machine_id == ordinary.id


def test_printer_payload_is_preserved_through_the_service_submission_boundary():
    space = make_space("b3-printer-boundary")
    target = printer(space)
    payload = {"requested_material": "PLA", "requested_color": "Blue", "quantity": 1}
    from apps.machines.public_service_serializers import PublicMachineServiceSubmitSerializer

    serializer = PublicMachineServiceSubmitSerializer(data={"machine_id": target.id, "title": "Boundary", "capability_payload": payload})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["capability_payload"] == payload
