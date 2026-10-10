import pytest
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.devices.errors_printers import PrinterConflict
from apps.devices.models import PrinterJob
from apps.devices.services_printer_jobs import create_job
from apps.devices.services_printer_reports import telemetry
from tests.devices.printer_helpers import printer_case, signed_post
from tests.module_helpers import disable_module
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db


def test_job_identity_is_explicit_unique_and_request_title_is_not_snapshotted():
    case = printer_case("printer-job-identity")
    assert case["job"].service_request_name == f"Request {case['request'].pk}"
    with pytest.raises(PrinterConflict):
        create_job(case["actor"], case["space"].pk, binding_id=case["binding"].pk,
                   service_request_id=case["request"].pk, external_job_id="another-external-id")
    other = printer_case("printer-job-wrong-request")
    with pytest.raises(ValidationError):
        create_job(case["actor"], case["space"].pk, binding_id=case["binding"].pk,
                   service_request_id=other["request"].pk, external_job_id="wrong")


def test_telemetry_after_short_lease_expiry_is_advisory_and_audited_without_user_actor():
    case = printer_case("printer-job-telemetry", leased=True)
    from apps.devices.models import DeviceCommand
    DeviceCommand.objects.filter(pk=case["job"].command_id).update(lease_expires_at=timezone.now() - timedelta(hours=2))
    row = telemetry(case["principal"], case["job"].pk, {"external_job_id": case["job"].external_job_id, "telemetry_state": "idle", "progress_percent": 5})
    assert row.progress_percent == 5
    case["machine"].refresh_from_db()
    assert case["machine"].status == "running"
    audit = AuditLog.objects.get(action="devices.printer_telemetry_received", makerspace=case["space"])
    assert audit.actor_id is None and audit.meta["printer_job_id"] == str(row.pk)


def test_staff_lists_are_paginated_and_details_follow_tenant_scope():
    case = printer_case("printer-job-list")
    listing = case["client"].get(reverse("devices:admin-printer-job-list", args=[case["space"].pk]))
    assert listing.status_code == 200 and set(listing.data) == {"count", "next", "previous", "results"}
    other = printer_case("printer-job-foreign-list")
    assert other["client"].get(reverse("devices:admin-printer-job-detail", args=[case["job"].pk])).status_code == 404


def test_adapter_module_off_is_400_and_source_gate_refuses_delivery_and_results():
    case = printer_case("printer-job-module", leased=True)
    path = reverse("devices:device-printer-job-telemetry", args=[case["job"].pk])
    payload = {"external_job_id": case["job"].external_job_id, "telemetry_state": "running", "progress_percent": 1}
    disable_module(case["space"], "machine_service")
    assert signed_post(case, path, payload).status_code == 400
    assert case["client"].get(reverse("devices:admin-printer-job-list", args=[case["space"].pk])).status_code == 400
    frozen = printer_case("printer-job-source-gate", leased=True)
    close_gate(frozen["space"], make_actor("printer-job-gate"))
    assert signed_post(frozen, reverse("devices:device-command-lease"), {}).status_code == 423
    assert frozen["client"].post(reverse("devices:admin-printer-job-apply", args=[frozen["job"].pk]), {}, format="json").status_code == 423
    assert PrinterJob.objects.get(pk=frozen["job"].pk).reported_at is None
