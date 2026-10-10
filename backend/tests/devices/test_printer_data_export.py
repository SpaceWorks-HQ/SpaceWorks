import pytest
from django.db import connection, transaction
from django.contrib.auth import get_user_model

from apps.data_export.fields import ALWAYS_OMITTED, FIELDS
from apps.data_export.guards import validate_all
from apps.data_export.models import EXPORTED_MODEL_FIELDS
from apps.data_export.references import RELATIONAL_USER_FIELDS
from apps.data_export.types import Fidelity, Omitted
from apps.devices.models import DeviceCommand, PrinterDeviceBinding, PrinterJob, PrinterJobConsumption
from apps.devices.services_printer_apply import report_result
from apps.encryption.crypto import is_envelope
from apps.makerspaces.module_purge import purge_module
from tests.devices.printer_helpers import printer_case, result_payload
from tests.encryption.conftest import enabled_encryption
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db


def test_printer_models_fields_user_edges_and_no_lease_credentials_are_exported():
    validate_all()
    for model in (DeviceCommand, PrinterDeviceBinding, PrinterJob, PrinterJobConsumption):
        fields = {field.name for field in model._meta.get_fields() if field.concrete or field.many_to_many}
        assert fields == set(EXPORTED_MODEL_FIELDS[model._meta.label].split())
    for edge in (("devices.DeviceCommand", "created_by"), ("devices.PrinterDeviceBinding", "created_by"), ("devices.PrinterJob", "processed_by")):
        assert edge in RELATIONAL_USER_FIELDS
    assert ("devices.DeviceCommand", "lease_token_digest") in ALWAYS_OMITTED
    assert all(isinstance(FIELDS[(fidelity, "devices.DeviceCommand", "lease_token_digest")], Omitted) for fidelity in Fidelity)


def test_failure_note_is_encrypted_and_not_copied_into_audit():
    with enabled_encryption():
        case = printer_case("printer-report-pii", leased=True)
        reason = "Contact person@example.test about fault"
        report_result(case["principal"], case["job"].pk, result_payload(case, outcome="failed", failure_reason=reason, percent_complete=20))
        with connection.cursor() as cursor:
            cursor.execute("SELECT failure_reason FROM devices_printerjob WHERE id = %s", [case["job"].pk])
            raw = cursor.fetchone()[0]
        assert is_envelope(raw) and reason not in raw
        assert PrinterJob.objects.get(pk=case["job"].pk).failure_reason == reason
        from apps.audit.models import AuditLog
        assert all(reason not in str(row.meta) for row in AuditLog.objects.filter(action__startswith="devices."))


def test_device_purge_removes_all_printer_rows_and_retains_machine_workflow():
    case = printer_case("printer-purge", leased=True)
    disable_module(case["space"], "devices")
    root = get_user_model().objects.create_superuser("printer-purge-root", "root@example.test", "secret")
    counts = purge_module(case["space"], "devices", root)
    assert counts["printer_jobs"] == 1 and counts["device_commands"] == 1 and counts["printer_bindings"] == 1
    for model in (DeviceCommand, PrinterDeviceBinding, PrinterJob, PrinterJobConsumption):
        assert not model.objects.exists()
    case["request"].refresh_from_db()
    assert case["request"].status == "in_progress"


def test_adapter_deletion_nulls_live_links_without_erasing_printer_history():
    case = printer_case("printer-adapter-purge", leased=True)
    # The real module purge uses this transaction-local immutable-delete permission.
    request_id = case["request"].pk
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        case["request"].delete()
    job = PrinterJob.objects.get(pk=case["job"].pk)
    assert job.service_request_id is None and job.service_request_id_snapshot == request_id
    # It was acknowledged, so explicitly testing delivery of the same missing target uses
    # the target validator; cancelled ownership can never publish another result.
    from apps.devices.services_commands import validate_delivery_target
    with transaction.atomic():
        assert validate_delivery_target(case["space"], case["device"], job.command) is None
    assert DeviceCommand.objects.get(pk=job.command_id).status == "cancelled"


def test_mapped_report_write_is_fenced_in_service_and_raw_sql():
    from apps.encryption.write_fence import PiiWriteFenced, close_makerspace, reopen
    from django.db import DatabaseError
    case = printer_case("printer-pii-fenced", leased=True)
    operation = close_makerspace(case["space"].pk, "enable_transition", case["actor"].pk)
    try:
        with pytest.raises(PiiWriteFenced):
            report_result(case["principal"], case["job"].pk, result_payload(case))
        with pytest.raises(DatabaseError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("UPDATE devices_printerjob SET failure_reason = %s WHERE id = %s", ["Fault", case["job"].pk])
        assert PrinterJob.objects.get(pk=case["job"].pk).reported_at is None
    finally:
        reopen(operation, case["actor"].pk)
