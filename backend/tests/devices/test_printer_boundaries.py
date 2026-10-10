"""Regression coverage for claim/effect crashes and current authority checks."""
from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.devices import services_printer_apply as adapter
from apps.devices.errors_printers import PrinterConflict
from apps.devices.models import Device, PrinterJob, PrinterJobConsumption
from apps.devices.services_commands import acknowledge, lease_command
from apps.devices.services_printer_jobs import create_job
from apps.devices.services_printer_reports import claim_result
from apps.machines.models import MachineConsumable, MakerspaceMachineTypePricing, ServiceRequestConsumption
from apps.payments.models import Payment
from tests.devices.printer_helpers import printer_case, result_payload, signed_post
from tests.return_helpers import make_member, make_product
from tests.test_machine_service_workflow import in_progress

pytestmark = pytest.mark.django_db(transaction=True)


def test_applied_marker_or_provenance_failure_rolls_back_stock_money_and_workflow(monkeypatch):
    case = printer_case("printer-marker-crash", auto=True, leased=True)
    stock = MachineConsumable.objects.create(machine=case["machine"], measurement="grams", label="Material", remaining=100)
    MakerspaceMachineTypePricing.objects.create(makerspace=case["space"], machine_type=case["machine"].machine_type,
                                               flat_fee=5, payment_enabled=True)
    case["space"].enabled_features = sorted(set(case["space"].enabled_features) | {"charges.enabled", "charges.machines"})
    case["space"].save(update_fields=["enabled_features"])
    original = adapter.record
    def crash(*args, **kwargs):
        if args[2] == "printer_result_applied":
            raise RuntimeError("crash between effect and provenance")
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter, "record", crash)
    payload = result_payload(case, consumptions=[{"machine_consumable_id": stock.pk, "quantity": "7"}])
    assert adapter.report_result(case["principal"], case["job"].pk, payload).state == "needs_review"
    case["request"].refresh_from_db()
    stock.refresh_from_db()
    assert case["request"].status == "in_progress" and stock.remaining == 100
    assert PrinterJobConsumption.objects.filter(job=case["job"]).count() == 1
    assert not ServiceRequestConsumption.objects.filter(service_request=case["request"]).exists()
    assert not Payment.objects.filter(subject_type="machine_service_request", subject_id=case["request"].pk).exists()
    assert not AuditLog.objects.filter(action="devices.printer_result_applied").exists()
    monkeypatch.setattr(adapter, "record", original)
    assert adapter.report_result(case["principal"], case["job"].pk, payload).state == "needs_review"
    assert adapter.approve_report(case["actor"], case["job"].pk).state == "applied"
    stock.refresh_from_db()
    assert stock.remaining == Decimal("93")
    assert Payment.objects.filter(subject_type="machine_service_request", subject_id=case["request"].pk).count() == 1


def test_claim_provenance_failure_rolls_back_whole_claim(monkeypatch):
    case = printer_case("printer-claim-crash", leased=True)
    from apps.devices import services_printer_reports as reports
    def crash(*args, **kwargs):
        raise RuntimeError("claim provenance unavailable")
    monkeypatch.setattr(reports, "record", crash)
    with pytest.raises(RuntimeError):
        claim_result(case["principal"], case["job"].pk, result_payload(case))
    job = PrinterJob.objects.get(pk=case["job"].pk)
    assert job.reported_at is None and job.state == "awaiting" and not job.consumptions.exists()


def test_wrong_machine_duplicate_and_fractional_count_consumptions_are_rejected():
    case = printer_case("printer-wrong-material", leased=True)
    other = printer_case("printer-foreign-material")
    foreign = MachineConsumable.objects.create(machine=other["machine"], measurement="grams", label="Foreign", remaining=100)
    count = MachineConsumable.objects.create(machine=case["machine"], measurement="count", product=make_product(case["space"], total_quantity=10))
    for rows in ([{"machine_consumable_id": foreign.pk, "quantity": "1"}],
                 [{"machine_consumable_id": count.pk, "quantity": "0.5"}],
                 [{"machine_consumable_id": count.pk, "quantity": "1"}] * 2):
        with pytest.raises(ValidationError):
            claim_result(case["principal"], case["job"].pk, result_payload(case, consumptions=rows))
    assert PrinterJob.objects.get(pk=case["job"].pk).reported_at is None


def test_canonical_consumption_order_replays_and_operation_id_cannot_bind_another_job():
    case = printer_case("printer-operation-reuse", leased=True)
    stocks = [MachineConsumable.objects.create(machine=case["machine"], measurement="grams", label=str(i), remaining=100) for i in range(2)]
    rows = [{"machine_consumable_id": stock.pk, "quantity": "1.00"} for stock in stocks]
    payload = result_payload(case, consumptions=rows)
    adapter.report_result(case["principal"], case["job"].pk, payload)
    assert adapter.report_result(case["principal"], case["job"].pk, {**payload, "consumptions": rows[::-1]}).state == "needs_review"
    adapter.approve_report(case["actor"], case["job"].pk)
    request = in_progress(case["space"], actor=case["actor"], target=case["machine"])
    job = create_job(case["actor"], case["space"].pk, binding_id=case["binding"].pk,
                     service_request_id=request.pk, external_job_id=uuid4().hex)
    lease = lease_command(case["principal"])
    acknowledge(case["principal"], job.command_id, lease["lease_token"])
    with pytest.raises(PrinterConflict):
        claim_result(case["principal"], job.pk, {**payload, "external_job_id": job.external_job_id, "consumptions": []})


def test_staff_approval_rechecks_machine_scope_and_device_kind_is_checked_per_report():
    case = printer_case("printer-current-scope", leased=True)
    adapter.report_result(case["principal"], case["job"].pk, result_payload(case))
    manager = make_member("printer-unscoped-approver", case["space"], membership_role="machine_manager", role=User.Role.REQUESTER)
    case["client"].force_authenticate(manager)
    response = case["client"].post(reverse("devices:admin-printer-job-apply", args=[case["job"].pk]), {}, format="json")
    assert response.status_code == 404
    Device.objects.filter(pk=case["device"].pk).update(kind="generic")
    response = signed_post(case, reverse("devices:device-printer-job-result", args=[case["job"].pk]), result_payload(case))
    assert response.status_code == 403
