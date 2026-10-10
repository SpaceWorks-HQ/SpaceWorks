from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections
from rest_framework.exceptions import ValidationError

from apps.devices.models import PrinterJob
from apps.devices.services_printer_apply import report_result
from apps.machines.models import MachineConsumableAdjustment
from apps.machines.service_consumable_pools import create_pool, reserve_for_request
from tests.devices.printer_helpers import printer_case, result_payload

pytestmark = pytest.mark.django_db(transaction=True)


def test_actual_weight_reconciles_reserved_pool_once():
    case = printer_case("printer-reconcile", auto=True, leased=True)
    pool = create_pool(case["space"], case["actor"], material="Material", initial_grams="100", machine=case["machine"])
    reserve_for_request(case["request"], case["actor"], pool=pool, planned_grams="20", machine=case["machine"])
    payload = result_payload(case, actual_grams="12")
    assert report_result(case["principal"], case["job"].pk, payload).state == "applied"
    assert report_result(case["principal"], case["job"].pk, payload).state == "applied"
    pool.refresh_from_db()
    assert pool.remaining_grams == Decimal("88")
    assert MachineConsumableAdjustment.objects.filter(consumable_pool=pool, kind="reconcile").count() == 1


def test_reserved_pool_requires_explicit_matching_measurement():
    case = printer_case("printer-measure-required", leased=True)
    pool = create_pool(case["space"], case["actor"], material="Material", initial_grams="100", machine=case["machine"])
    reserve_for_request(case["request"], case["actor"], pool=pool, planned_grams="20", machine=case["machine"])
    for changes in ({}, {"actual_quantity": "12"}):
        with pytest.raises(ValidationError):
            report_result(case["principal"], case["job"].pk, result_payload(case, **changes))
    assert PrinterJob.objects.get(pk=case["job"].pk).reported_at is None


def test_same_terminal_report_from_concurrent_workers_has_one_workflow_effect():
    case = printer_case("printer-concurrent-result", auto=True, leased=True)
    payload = result_payload(case)
    def report(_):
        close_old_connections()
        try:
            return report_result(case["principal"], case["job"].pk, payload).state
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        states = list(pool.map(report, range(2)))
    assert states == ["applied", "applied"]
    from apps.audit.models import AuditLog
    assert AuditLog.objects.filter(action="machine_service.completed", target_id=str(case["request"].pk)).count() == 1


def test_failed_generic_quantity_reconciles_actual_use_without_payment():
    case = printer_case("printer-generic-failure", auto=True, leased=True)
    case["request"].metering_unit = "count"
    case["request"].save(update_fields=["metering_unit"])
    pool = create_pool(case["space"], case["actor"], material="Units", quantity="100", unit="count", machine=case["machine"])
    reserve_for_request(case["request"], case["actor"], pool=pool, planned_quantity="20", machine=case["machine"])
    payload = result_payload(case, outcome="failed", failure_reason="Fault", percent_complete=50, actual_quantity="7")
    assert report_result(case["principal"], case["job"].pk, payload).state == "applied"
    assert report_result(case["principal"], case["job"].pk, payload).state == "applied"
    pool.refresh_from_db()
    assert pool.remaining_grams == Decimal("93")
    assert MachineConsumableAdjustment.objects.filter(consumable_pool=pool, kind="reconcile").count() == 1
    from apps.payments.models import Payment
    assert not Payment.objects.filter(subject_type="machine_service_request", subject_id=case["request"].pk).exists()
