"""Lane D raw projection cannot preserve live delivery or unprocessed authority."""
import pytest
from django.db import connection

from apps.devices.models import DeviceCommand, PrinterDeviceBinding, PrinterJob
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from tests.devices.printer_helpers import printer_case

pytestmark = pytest.mark.django_db


def raw_row(model, pk):
    with connection.cursor() as cursor:
        fields = model._meta.concrete_fields
        cursor.execute(
            f'SELECT {", ".join(field.column for field in fields)} FROM {model._meta.db_table} WHERE id = %s', [pk]
        )
        return dict(zip((field.attname for field in fields), cursor.fetchone()))


@pytest.mark.parametrize("state,expected", [
    ("awaiting", "needs_review"), ("reported", "needs_review"), ("needs_review", "needs_review"),
    ("applied", "applied"), ("cancelled", "cancelled"),
])
def test_raw_dump_selects_conditional_printer_job_reset(state, expected):
    case = printer_case("printer-raw-" + state, leased=True)
    source = raw_row(PrinterJob, case["job"].pk)
    source["state"] = state
    assert sanitize_record(PrinterJob, source).values["state"] == expected
    command = sanitize_record(DeviceCommand, raw_row(DeviceCommand, case["job"].command_id)).values
    assert command["status"] == "cancelled" and command["lease_token_digest"] is None and command["lease_expires_at"] is None
    binding = sanitize_record(PrinterDeviceBinding, raw_row(PrinterDeviceBinding, case["binding"].pk)).values
    assert not binding["enabled"] and not binding["auto_apply_terminal"]
