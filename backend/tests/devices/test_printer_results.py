from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.utils import InternalError
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.devices.errors_printers import PrinterConflict
from apps.devices.models import Device, PrinterJob, PrinterJobConsumption
from apps.devices.services_printer_apply import approve_report, report_result
from apps.devices.services_printer_reports import claim_result
from apps.machines.models import MachineConsumable, MakerspaceMachineTypePricing, ServiceRequestConsumption
from apps.payments.models import Payment
from tests.devices.printer_helpers import printer_case, result_payload, signed_post

pytestmark = pytest.mark.django_db(transaction=True)


def test_manual_review_is_default_and_matching_retry_and_staff_approval_apply_once():
    case = printer_case("printer-manual-result", leased=True)
    payload = result_payload(case)
    claimed = report_result(case["principal"], case["job"].pk, payload)
    assert claimed.state == "needs_review"
    case["request"].refresh_from_db()
    assert case["request"].status == "in_progress"
    assert report_result(case["principal"], claimed.pk, payload).state == "needs_review"
    assert approve_report(case["actor"], claimed.pk).state == "applied"
    assert approve_report(case["actor"], claimed.pk).state == "applied"
    assert report_result(case["principal"], claimed.pk, payload).state == "applied"
    assert AuditLog.objects.filter(action="machine_service.completed", target_id=str(case["request"].pk)).count() == 1
    assert AuditLog.objects.get(action="devices.printer_result_applied").actor_id == case["actor"].pk


def test_auto_apply_debits_consumptions_and_authoritative_charge_exactly_once():
    case = printer_case("printer-auto-result", auto=True, leased=True)
    consumable = MachineConsumable.objects.create(machine=case["machine"], measurement="grams", label="Actual material", remaining=100)
    MakerspaceMachineTypePricing.objects.create(makerspace=case["space"], machine_type=case["machine"].machine_type, flat_fee=5, payment_enabled=True)
    case["space"].enabled_features = sorted(set(case["space"].enabled_features) | {"charges.enabled", "charges.machines"})
    case["space"].save(update_fields=["enabled_features"])
    payload = result_payload(case, consumptions=[{"machine_consumable_id": consumable.pk, "quantity": "7.50"}])
    assert report_result(case["principal"], case["job"].pk, payload).state == "applied"
    assert report_result(case["principal"], case["job"].pk, payload).state == "applied"
    consumable.refresh_from_db()
    assert consumable.remaining == Decimal("92.50")
    assert ServiceRequestConsumption.objects.filter(service_request=case["request"]).count() == 1
    payments = Payment.objects.filter(subject_type="machine_service_request", subject_id=case["request"].pk)
    assert payments.count() == 1 and payments.get().amount == Decimal("5.00")
    assert AuditLog.objects.get(action="devices.printer_result_applied").actor_id is None


def test_failed_result_passes_reason_percentage_and_never_creates_payment():
    case = printer_case("printer-failed-result", auto=True, leased=True)
    payload = result_payload(case, outcome="failed", failure_reason="Nozzle fault", percent_complete=40)
    assert report_result(case["principal"], case["job"].pk, payload).state == "applied"
    case["request"].refresh_from_db()
    assert (case["request"].status, case["request"].fail_percent_complete, case["request"].reason) == ("failed", 40, "Nozzle fault")
    assert not Payment.objects.filter(subject_type="machine_service_request", subject_id=case["request"].pk).exists()


def test_conflicting_report_payload_operation_or_external_identity_is_409():
    case = printer_case("printer-conflicting-result", leased=True)
    payload = result_payload(case)
    report_result(case["principal"], case["job"].pk, payload)
    for change in ({"actual_minutes": 99}, {"operation_id": str(uuid4())}, {"external_job_id": "wrong"}):
        with pytest.raises(PrinterConflict):
            report_result(case["principal"], case["job"].pk, {**payload, **change})
    assert AuditLog.objects.filter(action="devices.printer_result_claimed", makerspace=case["space"]).count() == 1


@pytest.mark.parametrize("change", [
    {"actual_minutes": -1}, {"actual_minutes": True}, {"actual_minutes": 1.5},
    {"operation_id": "not-a-uuid"}, {"consumptions": None}, {"price": 1},
    {"currency": "USD"}, {"amount": 1}, {"payment_status": "paid"},
    {"actual_quantity": "NaN"}, {"actual_grams": "Infinity"},
    {"outcome": "failed", "failure_reason": "  ", "percent_complete": 30},
    {"outcome": "failed", "failure_reason": "Fault", "percent_complete": 101},
    {"actual_grams": "1", "actual_quantity": "1"},
])
def test_invalid_or_device_pricing_input_is_rejected_before_claim(change):
    case = printer_case("printer-invalid-" + uuid4().hex[:10], leased=True)
    with pytest.raises(ValidationError):
        report_result(case["principal"], case["job"].pk, result_payload(case, **change))
    assert PrinterJob.objects.get(pk=case["job"].pk).reported_at is None


def test_workflow_failure_rolls_back_effects_keeps_claim_and_never_retries_automatically(monkeypatch):
    case = printer_case("printer-rollback-result", auto=True, leased=True)
    from apps.devices import services_printer_apply as adapter
    original = adapter.workflow.complete
    def crash(row, actor, **kwargs):
        original(row, actor, **kwargs)
        raise RuntimeError("simulated crash after workflow effect")
    monkeypatch.setattr(adapter.workflow, "complete", crash)
    payload = result_payload(case)
    result = report_result(case["principal"], case["job"].pk, payload)
    assert result.state == "needs_review" and result.reported_at is not None
    case["request"].refresh_from_db()
    assert case["request"].status == "in_progress"
    assert not AuditLog.objects.filter(action="machine_service.completed", target_id=str(case["request"].pk)).exists()
    monkeypatch.setattr(adapter.workflow, "complete", original)
    assert report_result(case["principal"], case["job"].pk, payload).state == "needs_review"
    assert approve_report(case["actor"], case["job"].pk).state == "applied"


def test_crash_between_claim_and_apply_resumes_from_durable_report():
    case = printer_case("printer-resume-result", auto=True, leased=True)
    payload = result_payload(case)
    job, claimed = claim_result(case["principal"], case["job"].pk, payload)
    assert claimed and job.state == "reported"
    assert report_result(case["principal"], job.pk, payload).state == "applied"
    assert AuditLog.objects.filter(action="devices.printer_result_claimed", makerspace=case["space"]).count() == 1


def test_report_cannot_finish_unacknowledged_or_rotated_command():
    case = printer_case("printer-unacked-result")
    with pytest.raises(PrinterConflict):
        report_result(case["principal"], case["job"].pk, result_payload(case))
    Device.objects.filter(pk=case["device"].pk).update(key_version=2)
    with pytest.raises(PermissionDenied):
        report_result(case["principal"], case["job"].pk, result_payload(case))


def test_signed_result_api_uses_device_principal_and_keeps_actor_null():
    case = printer_case("printer-signed-result", auto=True, leased=True)
    response = signed_post(case, reverse("devices:device-printer-job-result", args=[case["job"].pk]), result_payload(case))
    assert response.status_code == 200 and response.data["state"] == "applied"
    assert AuditLog.objects.get(action="devices.printer_result_claimed").actor_id is None


def test_claimed_report_is_immutable_in_database_including_consumption_rows():
    case = printer_case("printer-report-guard", leased=True)
    pool = MachineConsumable.objects.create(machine=case["machine"], measurement="grams", label="Stock", remaining=100)
    report_result(case["principal"], case["job"].pk, result_payload(case, consumptions=[{"machine_consumable_id": pool.pk, "quantity": "2"}]))
    for model, updates in ((PrinterJob, {"actual_minutes": 999}), (PrinterJobConsumption, {"quantity": 99})):
        with pytest.raises(InternalError):
            with transaction.atomic():
                model.objects.all().update(**updates)
    with pytest.raises(InternalError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE devices_printerjob SET external_job_id = 'forged' WHERE id = %s", [case["job"].pk])
    assert PrinterJob.objects.get(pk=case["job"].pk).actual_minutes == 15
