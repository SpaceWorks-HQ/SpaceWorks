from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.machines.models import Machine, MachineType, MachineUsageEntry
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule
from apps.operations import reports
from tests.return_helpers import make_member, make_space


pytestmark = pytest.mark.django_db


def _setup(slug="analytics-fablab"):
    space = make_space(slug)
    manager = make_member(f"{slug}-manager", space)
    machine_type = MachineType.objects.create(makerspace=space, slug=f"{slug}-type", name="Laser")
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Cutter")
    return space, manager, machine


def test_detailed_fablab_metrics_and_decimal_contract():
    space, manager, machine = _setup()
    retired = Machine.objects.create(makerspace=space, machine_type=machine.machine_type, name="Retired", is_active=False)
    MachineUsageEntry.objects.create(machine=machine, hours=Decimal("1.25"), note="private", logged_by=manager)
    MachineUsageEntry.objects.create(machine=retired, hours=Decimal("2.50"))
    event = Event.objects.create(
        makerspace=space, title="Workshop", starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(hours=2), status=Event.Status.COMPLETED,
        capacity=10,
    )
    for index, status in enumerate(EventRegistration.Status.values):
        EventRegistration.objects.create(event=event, name=f"Private {index}", email=f"p{index}@x.com", phone="1", status=status)
    start = timezone.now() - timedelta(hours=1)
    end = start + timedelta(hours=10)
    bookable = BookableSpace.objects.create(makerspace=space, name="Bench", kind=BookableSpace.Kind.BENCH)
    Booking.objects.create(space=bookable, name="Private", email="booker@x.com", phone="1", starts_at=start - timedelta(hours=1), ends_at=start + timedelta(hours=2), status=Booking.Status.COMPLETED)
    Booking.objects.create(space=bookable, name="Private 2", email="booker2@x.com", phone="1", starts_at=start + timedelta(hours=2), ends_at=start + timedelta(hours=4), status=Booking.Status.NO_SHOW)
    MaintenanceLog.objects.create(machine=machine, performed_by=manager, performed_at=start, summary="private", cost=Decimal("10.10"))
    MaintenanceLog.objects.create(machine=machine, performed_by=manager, performed_at=start + timedelta(days=2), summary="private", cost=None)
    MaintenanceSchedule.objects.create(machine=machine, description="private", interval_days=7, next_due=timezone.localdate() - timedelta(days=1))

    usage = reports.report_data("machine-usage", space.id)["typed_rows"]
    assert usage[0]["machine_name"] == "Retired"
    assert usage[0]["usage_hours"] == "2.50"
    assert usage[0]["is_active"] is False
    attendance = reports.report_data("event-attendance", space.id)["typed_rows"][0]
    assert (attendance["registrations"], attendance["confirmed"], attendance["attendance_rate_percent"]) == (6, 2, 50.0)
    assert attendance["pending_approval"] == attendance["rejected"] == 1
    booking = reports.report_data("booking-utilization", space.id, date_range=(start, end))["typed_rows"][0]
    assert booking["reserved_hours"] == "4.00"
    assert booking["completed_hours"] == "2.00"
    assert booking["reservation_utilization_percent"] == 40.0
    assert booking["no_show_rate_percent"] == 50.0
    maintenance = reports.report_data("maintenance-activity", space.id)["typed_rows"][0]
    assert maintenance["log_count"] == 2
    assert maintenance["costed_log_count"] == 1
    assert maintenance["total_cost"] == "10.10"
    assert maintenance["average_cost"] == "10.10"
    assert maintenance["average_interval_days"] == 2.0
    assert maintenance["overdue_schedules"] == 1


@pytest.mark.parametrize("key", ["machine-usage", "event-attendance", "booking-utilization", "maintenance-activity", "fablab-health"])
def test_every_aggregate_excludes_reports_disabled_hidden_and_archived(key):
    eligible, _, _ = _setup(f"eligible-{key}")
    if key == "event-attendance":
        Event.objects.create(
            makerspace=eligible, title="Eligible event", starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=1),
        )
    if key == "booking-utilization":
        BookableSpace.objects.create(makerspace=eligible, name="Eligible space")
    disabled, _, _ = _setup(f"disabled-{key}")
    disabled.enabled_modules = [module for module in disabled.enabled_modules if module != "reports"]
    disabled.save(update_fields=["enabled_modules"])
    hidden, _, _ = _setup(f"hidden-{key}")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    archived, _, _ = _setup(f"archived-{key}")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])

    rows = reports.report_data(key)["typed_rows"]
    ids = {row["makerspace_id"] for row in rows}
    assert eligible.id in ids
    assert disabled.id not in ids
    assert hidden.id not in ids
    assert archived.id not in ids


def test_health_isolates_iteration_failure_and_disabled_module(monkeypatch):
    space, _, _ = _setup("health-isolation")
    space.enabled_modules = [module for module in space.enabled_modules if module != "bookings"]
    space.save(update_fields=["enabled_modules"])

    def broken(_ids):
        yield {"makerspace_id": space.id, "events_in_period": 99}
        raise RuntimeError("iteration failure")

    monkeypatch.setattr("apps.operations.reports_health._event_rows", lambda ids, date_range: broken(ids))
    monkeypatch.setattr("apps.operations.reports_health._booking_rows", lambda *args: pytest.fail("disabled bookings queried"))
    row = reports.report_data("fablab-health", space.id)["typed_rows"][0]
    assert row["events_enabled"] is True
    assert row["events_available"] is False
    assert row["events_in_period"] is None
    assert row["bookings_enabled"] is False
    assert row["bookings_available"] is False
    assert row["bookings_reserved_hours"] is None
    assert row["machines_available"] is True
