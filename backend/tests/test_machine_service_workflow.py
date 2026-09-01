from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import close_old_connections, transaction
from django.test import override_settings

from apps.audit.models import AuditLog
from apps.inventory import availability
from apps.machines import role_scope, service_workflow_actions as service_workflow
from apps.machines.models import (
    Machine,
    MachineConsumable,
    MachineServiceRequest,
    MachineType,
    ServiceRequestConsumption,
)
from apps.machines.service_errors import (
    ServiceConsumptionInvalid,
    ServiceInsufficientStock,
    ServiceInvalidTransition,
    ServiceMachineUnavailable,
)
from apps.machines.service_workflow import accept, collect, complete, fail, reject, start, submit
from tests.return_helpers import make_product, make_space, make_user


pytestmark = pytest.mark.django_db


def machine(space, name="Service machine", **kwargs):
    kind = MachineType.objects.create(
        makerspace=space, slug=f"service-{space.id}-{uuid4().hex[:8]}", name="Service type"
    )
    return Machine.objects.create(makerspace=space, machine_type=kind, name=name, **kwargs)


def request(space, *, target=None, actor=None):
    return submit(
        target or machine(space), make_user(f"requester-{space.id}-{uuid4().hex[:8]}"), actor=actor,
        requester_name="Requester", contact_email="requester@example.com",
        contact_phone="123", title="Repair it",
    )


def in_progress(space, *, actor=None, target=None):
    row = request(space, target=target, actor=actor)
    accept(row, actor)
    return start(
        row,
        actor,
        role_scope.EXEMPT,
        machine_id=(target or row.bucket.machine).pk,
    )


def test_allowed_edges_are_audited_and_notified_after_commit(monkeypatch):
    space, actor = make_space("service-workflow-edges"), make_user("service-manager")
    notices = []
    callbacks = []
    monkeypatch.setattr("apps.machines.service_workflow_helpers.notify_service_status", lambda row, event: notices.append(event))
    monkeypatch.setattr("apps.machines.service_workflow_helpers.transaction.on_commit", callbacks.append)
    with transaction.atomic():
        row = request(space, actor=actor)
        assert notices == []
    assert len(callbacks) == 1
    callbacks.pop()()
    assert notices == ["submitted"]
    accept(row, actor, estimated_minutes=12, note="Reviewed")
    start(row, actor, role_scope.EXEMPT, machine_id=row.bucket.machine_id)
    complete(row, actor, actual_minutes=10, consumptions=[])
    collect(row, actor)
    for callback in callbacks:
        callback()
    row.refresh_from_db()
    assert row.status == MachineServiceRequest.Status.COLLECTED
    assert {
        "machine_service.submitted", "machine_service.accepted", "machine_service.assigned",
        "machine_service.started", "machine_service.completed", "machine_service.collected",
    } <= set(AuditLog.objects.filter(target_id=str(row.pk)).values_list("action", flat=True))
    assert notices == ["submitted", "accepted", "started", "completed", "collected"]


def test_reject_and_fail_edges_record_required_data():
    space, actor = make_space("service-workflow-reject-fail"), make_user("service-manager-rf")
    rejected = request(space, actor=actor)
    reject(rejected, actor, reason="Not suitable")
    rejected.refresh_from_db()
    assert (rejected.status, rejected.reason) == (MachineServiceRequest.Status.REJECTED, "Not suitable")
    failed = in_progress(space, actor=actor)
    fail(failed, actor, reason="Tool fault", percent_complete=40, actual_minutes=8, consumptions=[])
    failed.refresh_from_db()
    assert (failed.status, failed.fail_percent_complete, failed.actual_minutes, failed.failed_at) == (
        MachineServiceRequest.Status.FAILED, 40, 8, failed.failed_at,
    )
    assert AuditLog.objects.filter(target_id=str(failed.pk), action="machine_service.failed").exists()


@pytest.mark.parametrize("status,operation", [
    (MachineServiceRequest.Status.PENDING, lambda row, actor: collect(row, actor)),
    (MachineServiceRequest.Status.ACCEPTED, lambda row, actor: complete(row, actor, actual_minutes=0, consumptions=[])),
    (MachineServiceRequest.Status.IN_PROGRESS, lambda row, actor: accept(row, actor)),
    (MachineServiceRequest.Status.COMPLETED, lambda row, actor: reject(row, actor, reason="late")),
    (MachineServiceRequest.Status.REJECTED, lambda row, actor: accept(row, actor)),
    (MachineServiceRequest.Status.FAILED, lambda row, actor: collect(row, actor)),
    (MachineServiceRequest.Status.COLLECTED, lambda row, actor: start(row, actor, role_scope.EXEMPT, machine_id=row.bucket.machine_id)),
])
def test_forbidden_edges_raise_typed_error(status, operation):
    space, actor = make_space(f"service-bad-{status}"), make_user(f"service-manager-{status}")
    row = request(space, actor=actor)
    if status in {MachineServiceRequest.Status.ACCEPTED, MachineServiceRequest.Status.IN_PROGRESS,
                  MachineServiceRequest.Status.COMPLETED, MachineServiceRequest.Status.COLLECTED}:
        accept(row, actor)
    if status in {MachineServiceRequest.Status.IN_PROGRESS, MachineServiceRequest.Status.COMPLETED,
                  MachineServiceRequest.Status.COLLECTED}:
        start(row, actor, role_scope.EXEMPT, machine_id=row.bucket.machine_id)
    if status in {MachineServiceRequest.Status.COMPLETED, MachineServiceRequest.Status.COLLECTED}:
        complete(row, actor, actual_minutes=0, consumptions=[])
    if status == MachineServiceRequest.Status.COLLECTED:
        collect(row, actor)
    if status == MachineServiceRequest.Status.REJECTED:
        reject(row, actor, reason="No")
    if status == MachineServiceRequest.Status.FAILED:
        accept(row, actor); start(row, actor, role_scope.EXEMPT, machine_id=row.bucket.machine_id)
        fail(row, actor, reason="No", percent_complete=0, actual_minutes=0, consumptions=[])
    with pytest.raises(ServiceInvalidTransition):
        operation(row, actor)


def test_status_queryset_updates_are_workflow_guarded():
    row = request(make_space("service-status-guard"))
    with pytest.raises(RuntimeError, match="workflow-managed"):
        MachineServiceRequest.objects.filter(pk=row.pk).update(status="accepted")


def test_submit_acquires_the_pii_fence_before_locking_the_machine(monkeypatch):
    space = make_space("service-fence-before-lock")
    target = machine(space)
    calls = []
    original = service_workflow._locked_submission_machine

    monkeypatch.setattr(
        "apps.machines.service_workflow_actions._assert_submission_write_allowed",
        lambda value: calls.append(("fence", value.pk)),
    )

    def locked(value):
        assert calls == [("fence", target.pk)]
        return original(value)

    monkeypatch.setattr("apps.machines.service_workflow_actions._locked_submission_machine", locked)
    request(space, target=target)


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
def test_submit_enforces_managed_open_and_daily_caps():
    open_limited = make_space("service-cap-open")
    open_limited.resource_limit_overrides = {"machine_service_open": 0, "machine_service_submit": 10}
    open_limited.save(update_fields=["resource_limit_overrides"])
    with pytest.raises(Exception, match="limit"):
        request(open_limited)
    daily_limited = make_space("service-cap-daily")
    daily_limited.resource_limit_overrides = {"machine_service_open": 10, "machine_service_submit": 0}
    daily_limited.save(update_fields=["resource_limit_overrides"])
    with pytest.raises(Exception, match="limit"):
        request(daily_limited)


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_submit_caps_are_dormant_on_self_host():
    space = make_space("service-cap-self-host")
    space.resource_limit_overrides = {"machine_service_open": 0, "machine_service_submit": 0}
    space.save(update_fields=["resource_limit_overrides"])
    assert request(space).status == MachineServiceRequest.Status.PENDING


def test_count_consumption_debits_inventory_once_and_rejects_fractional(monkeypatch):
    space, actor = make_space("service-count"), make_user("service-count-manager")
    row = in_progress(space, actor=actor)
    product = make_product(space, name="Bits", available_quantity=4, total_quantity=4)
    consumable = MachineConsumable.objects.create(machine=row.assigned_machine, measurement="count", product=product)
    calls, original_consume = [], availability.consume_available

    def consume(product, quantity, reason, actor):
        calls.append((product.pk, quantity, actor.pk))
        return original_consume(product, quantity, reason, actor)

    monkeypatch.setattr(availability, "consume_available", consume)
    complete(row, actor, actual_minutes=2, consumptions=[{"machine_consumable_id": consumable.pk, "quantity": 2}])
    product.refresh_from_db()
    assert product.available_quantity == 2
    assert calls == [(product.pk, 2, actor.pk)]
    snapshot = ServiceRequestConsumption.objects.get(service_request=row)
    assert (snapshot.measurement, snapshot.quantity, snapshot.outcome) == ("count", Decimal("2.00"), "completed")
    with pytest.raises(ServiceInvalidTransition):
        complete(row, actor, actual_minutes=2, consumptions=[{"machine_consumable_id": consumable.pk, "quantity": 2}])
    bad = in_progress(space, actor=actor)
    bad_consumable = MachineConsumable.objects.create(
        machine=bad.assigned_machine, measurement="count", product=product
    )
    with pytest.raises(ServiceConsumptionInvalid, match="whole"):
        complete(bad, actor, actual_minutes=1, consumptions=[{"machine_consumable_id": bad_consumable.pk, "quantity": "1.5"}])


def test_insufficient_count_stock_rolls_back_and_grams_are_exact():
    space, actor = make_space("service-stock"), make_user("service-stock-manager")
    row = in_progress(space, actor=actor)
    product = make_product(space, name="Scarce", available_quantity=1, total_quantity=1)
    count = MachineConsumable.objects.create(machine=row.assigned_machine, measurement="count", product=product)
    with pytest.raises(ServiceInsufficientStock):
        complete(row, actor, actual_minutes=5, consumptions=[{"machine_consumable_id": count.pk, "quantity": 2}])
    row.refresh_from_db(); product.refresh_from_db()
    assert row.status == MachineServiceRequest.Status.IN_PROGRESS and product.available_quantity == 1
    grams = MachineConsumable.objects.create(machine=row.assigned_machine, measurement="grams", label="Resin", remaining="12.50")
    complete(row, actor, actual_minutes=5, consumptions=[{"machine_consumable_id": grams.pk, "quantity": "2.25"}])
    grams.refresh_from_db()
    assert grams.remaining == Decimal("10.25")
    overdraw = in_progress(space, actor=actor)
    too_much = MachineConsumable.objects.create(machine=overdraw.assigned_machine, measurement="grams", label="Powder", remaining="1")
    with pytest.raises(ServiceInsufficientStock):
        complete(overdraw, actor, actual_minutes=1, consumptions=[{"machine_consumable_id": too_much.pk, "quantity": 2}])


def test_failed_request_records_actual_partial_consumption_and_assigned_history():
    space, actor = make_space("service-failed-partial"), make_user("service-failed-manager")
    row = in_progress(space, actor=actor)
    grams = MachineConsumable.objects.create(machine=row.assigned_machine, measurement="grams", label="Clay", remaining="10")
    fail(row, actor, reason="Stopped", percent_complete=25, actual_minutes=6,
         consumptions=[{"machine_consumable_id": grams.pk, "quantity": 3}])
    row.refresh_from_db(); grams.refresh_from_db()
    assert row.status == "failed" and grams.remaining == Decimal("7.00")
    row.assigned_machine.is_active = False
    row.assigned_machine.save(update_fields=["is_active"])
    row.refresh_from_db()
    assert row.assigned_machine_id == grams.machine_id


@pytest.mark.parametrize("changes", [
    pytest.param({"is_active": False}, id="retired"),
    pytest.param({"status": Machine.Status.RUNNING}, id="running"),
    pytest.param({"status": Machine.Status.RESERVED}, id="reserved"),
    pytest.param({"status": Machine.Status.MAINTENANCE}, id="maintenance"),
    pytest.param({"status": Machine.Status.OFFLINE}, id="offline"),
])
def test_submit_and_start_refuse_unavailable_machines(changes):
    space = make_space(f"service-unavailable-{next(iter(changes.values()))}")
    target = machine(space, **changes)
    with pytest.raises(ServiceMachineUnavailable):
        request(space, target=target)
    available = machine(space, "Available")
    row = request(space, target=available)
    accept(row, None)
    target.status = Machine.Status.RUNNING
    target.save(update_fields=["status"])
    with pytest.raises(ServiceMachineUnavailable):
        start(row, None, role_scope.EXEMPT, machine_id=target.pk)
    other = machine(make_space("service-other-tenant"), "Other")
    with pytest.raises(ServiceMachineUnavailable):
        start(row, None, role_scope.EXEMPT, machine_id=other.pk)


@pytest.mark.django_db(transaction=True)
def test_contended_start_has_one_winner():
    space, actor = make_space("service-concurrency"), make_user("service-concurrency-manager")
    row = request(space, actor=actor); accept(row, actor)

    def transition():
        close_old_connections()
        try:
            local = MachineServiceRequest.objects.get(pk=row.pk)
            local_actor = type(actor).objects.get(pk=actor.pk)
            start(
                local,
                local_actor,
                role_scope.EXEMPT,
                machine_id=row.bucket.machine_id,
            )
            return "won"
        except ServiceInvalidTransition:
            return "lost"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: transition(), range(2)))
    assert sorted(outcomes) == ["lost", "won"]
