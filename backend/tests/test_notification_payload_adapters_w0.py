"""Domain adapters must identify their subject without copying template contact data."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

from apps.bookings import notifications as bookings
from apps.events import notifications as events
from apps.hardware_requests import notifications as hardware
from apps.machines import service_printing_emails as printing
from apps.machines.models import Machine
from apps.maintenance import notifications as maintenance
from apps.makerspaces import membership_notifications as members
from apps.makerspaces.models import Makerspace
from apps.integrations.lifecycle_data import lifecycle_data


def capture(monkeypatch, module):
    monkeypatch.setattr(module, "notify_lifecycle", lambda makerspace, **kwargs: kwargs["build"]())
    if hasattr(module, "render"):
        monkeypatch.setattr(module, "render", lambda *args, **kwargs: {"text_body": "Staff update"})
    if hasattr(module, "staff_emails_for_feature"):
        monkeypatch.setattr(module, "staff_emails_for_feature", lambda *args, **kwargs: [])


def return_row(monkeypatch, model, row):
    query = Mock()
    query.get.return_value = row
    query.prefetch_related.return_value = query
    monkeypatch.setattr(model.objects, "select_related", Mock(return_value=query))


def test_hardware_adapter_identifies_request_and_charge(monkeypatch):
    capture(monkeypatch, hardware)
    row = NS(pk=12, makerspace=NS(), makerspace_id=7, status="accepted")
    return_row(monkeypatch, hardware.HardwareRequest, row)
    monkeypatch.setattr(hardware, "_email_deliveries", lambda *args: ())
    payload = hardware.notify_request_accepted(row)
    assert payload.data == {"request_id": 12}
    payload = hardware.notify_loan_charge(row, "deposit_raised", NS(pk=19, amount=10, currency="inr"))
    assert payload.data == {"request_id": 12, "payment_id": 19}


def test_booking_adapter_identifies_booking_and_space(monkeypatch):
    capture(monkeypatch, bookings)
    context = {"email": "private@example.test"}
    monkeypatch.setattr(bookings, "bookings_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(bookings, "_effective_toggle", lambda row: False)
    row = NS(pk=21, space_id=22, space=NS(makerspace=NS()))
    return_row(monkeypatch, bookings.Booking, row)
    payload = bookings.notify_booking_status(row, "confirmed")
    assert payload.context == context
    assert payload.data == {"booking_id": 21, "space_id": 22}


def test_event_adapter_identifies_occurrence_series_and_registration(monkeypatch):
    capture(monkeypatch, events)
    monkeypatch.setattr(events, "events_context", lambda *args, **kwargs: {"name": "Private registrant"})
    row = NS(pk=31, series_id=32)
    return_row(monkeypatch, events.Event, row)
    monkeypatch.setattr(events.EventRegistration.objects, "get", lambda **kwargs: NS(pk=33))
    payload = events._notify_makerspace(31, NS(), "registration_approved", 33, sync=True)
    assert payload.data == {"event_id": 31, "series_id": 32, "registration_id": 33}


def test_maintenance_adapter_identifies_machine_schedule_and_completion_log(monkeypatch):
    capture(monkeypatch, maintenance)
    machine = NS(pk=41, makerspace=NS(), machine_type=NS(), machine_type_id=42)
    schedule = maintenance.MaintenanceSchedule(pk=43)
    schedule.machine = Machine(pk=41, makerspace=Makerspace(pk=7))
    # The adapter only reads the actual model to distinguish schedule from log.
    return_row(monkeypatch, maintenance.MaintenanceSchedule, NS(pk=43, machine=machine))
    monkeypatch.setattr(maintenance.MaintenanceLog.objects, "get", lambda **kwargs: NS(pk=44))
    monkeypatch.setattr(maintenance, "maintenance_context", lambda *args, **kwargs: {})
    payload = maintenance.notify_maintenance_lifecycle(schedule, "schedule_completed", log_id=44)
    assert payload.data == {"machine_id": 41, "schedule_id": 43, "maintenance_log_id": 44}


def test_membership_adapters_identify_request_and_membership(monkeypatch):
    capture(monkeypatch, members)
    monkeypatch.setattr(members, "membership_context", lambda *args, **kwargs: {"email": "private@example.test"})
    row = NS(pk=51, makerspace=NS(), user=NS())
    return_row(monkeypatch, members.MembershipRequest, row)
    assert members.notify_membership_request_pending(row).data == {"membership_request_id": 51}
    return_row(monkeypatch, members.MakerspaceMembership, row)
    assert members.notify_member_joined(row).data == {"membership_id": 51}


def test_printing_adapter_identifies_kernel_request(monkeypatch):
    from apps.machines.models import MachineServiceRequest

    capture(monkeypatch, printing)
    row = NS(pk=61, makerspace=NS())
    return_row(monkeypatch, MachineServiceRequest, row)
    monkeypatch.setattr(printing, "_is_printer_request", lambda row: True)
    monkeypatch.setattr(printing, "_requester_render", lambda *args: (None, None))
    monkeypatch.setattr(printing, "_staff_body", lambda *args: "Print update")
    payload = printing.notify_printer_service_status(row, "accepted", sync=True)
    assert payload.data == {"machine_service_request_id": 61}


def test_structured_ids_refuse_contact_credentials_and_invalid_identifiers():
    assert lifecycle_data({
        "request_id": 12, "email": "private@example.test", "secret": "private",
        "booking_id": True, "event_id": "13", "series_id": -1, "payment_id": None,
    }) == {"request_id": 12}
