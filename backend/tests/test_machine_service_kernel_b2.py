"""B2 pooled-service and consumable-kernel behavior."""

from decimal import Decimal

import pytest
from django.db import connection, transaction

from apps.audit.models import AuditLog
from apps.machines import role_scope
from apps.machines.models import (
    Machine,
    MachineConsumableAdjustment,
    MachineServiceRequest,
    MachineType,
    ServiceQueue,
)
from apps.machines.service_consumable_pools import (
    correct_pool,
    create_pool,
    log_typed_manual_usage,
    reconcile_request,
    reserve_for_request,
)
from apps.machines.service_errors import ServiceMachineUnavailable
from apps.machines.service_queue_position import queue_positions_for
from apps.machines.service_workflow import accept, collect, start, submit
from apps.operations.report_registry import report_definition
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def machine(space, *, suffix="", type_row=None):
    type_row = type_row or MachineType.objects.create(
        makerspace=space, slug=f"kernel-{space.id}-{suffix}", name="Kernel type"
    )
    return Machine.objects.create(makerspace=space, machine_type=type_row, name=f"Machine {suffix}")


def pooled_request(queue, user=None):
    return submit(
        queue, user or make_user(f"kernel-requester-{queue.id}-{MachineServiceRequest.objects.count()}"),
        actor=None, requester_name="Requester", contact_email="requester@example.test", contact_phone="1", title="Pooled job",
    )


def test_pooled_intake_stays_unassigned_and_queue_ranking_is_accepted_first():
    space = make_space("kernel-queue-intake")
    kind = MachineType.objects.create(makerspace=space, slug="kernel-queue-type", name="Queued")
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=kind, name="Fabrication")
    pending, accepted = pooled_request(queue), pooled_request(queue)
    accept(accepted, make_user("kernel-queue-manager"))
    pending.refresh_from_db(); accepted.refresh_from_db()
    assert pending.assigned_machine_id is None and accepted.assigned_machine_id is None
    assert queue_positions_for([pending, accepted]) == {pending.id: 2, accepted.id: 1}


def test_pooled_allocation_locks_same_tenant_compatible_idle_machine_and_capacity():
    space, other = make_space("kernel-allocation"), make_space("kernel-allocation-other")
    kind = MachineType.objects.create(makerspace=space, slug="kernel-allocation-type", name="Queued")
    other_kind = MachineType.objects.create(makerspace=space, slug="kernel-allocation-other-type", name="Other")
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=kind, name="Fabrication", capacity=1)
    request = pooled_request(queue)
    accept(request, make_user("kernel-allocation-manager"))
    wrong_type, foreign, compatible = machine(space, suffix="wrong", type_row=other_kind), machine(other, suffix="foreign"), machine(space, suffix="right", type_row=kind)
    with pytest.raises(ServiceMachineUnavailable):
        start(request, make_user("kernel-allocation-start"), role_scope.EXEMPT, machine_id=wrong_type.id)
    with pytest.raises(ServiceMachineUnavailable):
        start(request, make_user("kernel-allocation-start-two"), role_scope.EXEMPT, machine_id=foreign.id)
    started = start(request, make_user("kernel-allocation-start-three"), role_scope.EXEMPT, machine_id=compatible.id)
    assert started.assigned_machine_id == compatible.id
    compatible.refresh_from_db()
    assert compatible.status == Machine.Status.RUNNING


def test_first_idle_queue_allocates_without_a_machine_id_and_correction_is_typed():
    space = make_space("kernel-first-idle")
    kind = MachineType.objects.create(makerspace=space, slug="kernel-first-idle-type", name="Queued")
    queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=kind, name="Automatic",
        allocation_policy=ServiceQueue.AllocationPolicy.FIRST_IDLE,
    )
    target = machine(space, suffix="automatic", type_row=kind)
    request, actor = pooled_request(queue), make_user("kernel-first-idle-actor")
    accept(request, actor)
    assert start(request, actor, role_scope.EXEMPT, machine_id=None).assigned_machine_id == target.id
    pool = create_pool(space, actor, material="PLA", initial_grams="1", machine=target)
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        correct_pool(pool, actor, quantity_delta="not-a-number", reason="Bad input")


def test_pool_reserve_reconcile_manual_correction_and_append_only_guards():
    space = make_space("kernel-pool")
    target = machine(space, suffix="pool")
    actor = make_user("kernel-pool-actor")
    request = submit(target, make_user("kernel-pool-requester"), actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Legacy still works")
    pool = create_pool(space, actor, material="PLA", color="Blue", initial_grams="100", machine=target)
    reserve_for_request(request, actor, pool=pool, planned_grams="20", machine=target)
    reconcile_request(request, actor, actual_grams="12")
    entry = log_typed_manual_usage(target, actor, duration_minutes=30, outcome="failed", percent_complete=50, reason="Calibration", grams="5", pool=pool)
    correct_pool(pool, actor, quantity_delta="3", reason="Measured remainder")
    pool.refresh_from_db(); request.refresh_from_db()
    assert (pool.remaining_grams, request.reserved_grams, request.actual_consumed_grams) == (Decimal("86.00"), Decimal("0.00"), Decimal("12.00"))
    assert entry.hours == Decimal("0.25")
    adjustments = list(pool.adjustments.values_list("kind", "quantity_delta"))
    assert adjustments == [("reserve", Decimal("-20.00")), ("reconcile", Decimal("8.00")), ("manual", Decimal("-5.00")), ("correction", Decimal("3.00"))]
    row = pool.adjustments.first()
    with pytest.raises(RuntimeError, match="append-only"):
        MachineConsumableAdjustment.objects.filter(pk=row.pk).update(reason="no")
    with pytest.raises(Exception, match="append-only/immutable"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("UPDATE machines_machineconsumableadjustment SET reason = 'no' WHERE id = %s", [row.id])
    assert AuditLog.objects.filter(action="machine_consumable_pool.reserve", target_id=str(row.id), makerspace=space).exists()


def test_payment_hook_reprint_provenance_and_registry_seam():
    space = make_space("kernel-payment")
    kind = MachineType.objects.create(makerspace=space, slug="kernel-payment-type", name="Paid", capability_config={"metering_unit": "minutes", "requires_booking": False})
    target = machine(space, suffix="payment", type_row=kind)
    actor = make_user("kernel-payment-actor")
    request = submit(target, make_user("kernel-payment-requester"), actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Paid job")
    accept(request, actor)
    start(request, actor, role_scope.EXEMPT, machine_id=target.id)
    from apps.machines.service_workflow import complete, create_reprint
    complete(request, actor, actual_minutes=1, consumptions=[])
    collect(request, actor)
    reprint = create_reprint(request, actor)
    request.refresh_from_db()
    # C.3: the Payment model is the sole payment authority; legacy payment_* are historic read-only
    # (accept no longer sets an amount, collect no longer marks paid, reprint never copies payment).
    # Reprint provenance and the report-registry seam are unaffected.
    assert reprint.reprint_of_id == request.id
    assert (request.payment_status, request.paid_at) == ("none", None)
    assert (reprint.payment_status, reprint.payment_amount) == ("none", None)
    assert report_definition("machine-service").builder_path == "apps.machines.service_reports.build_machine_service_report"
