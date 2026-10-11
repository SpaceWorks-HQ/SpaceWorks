from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.operations.views_dashboard_counts import build_dashboard
from tests.modules.family_helpers import account, client, family_space

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("family", ["events", "machines", "membership", "bookings", "inventory"])
def test_counts_query_only_enabled_families_and_keep_existing_rows(family):
    space = family_space(f"dashboard-{family}", *([] if family == "inventory" else [family]), loans=family == "inventory")
    other = family_space(f"dashboard-other-{family}", "events", "bookings", loans=True)
    borrower = account(f"dashboard-borrower-{family}")
    start = timezone.now() + timedelta(days=1)
    for tenant in [space, other]:
        InventoryProduct.objects.create(makerspace=tenant, name="Empty shelf", available_quantity=0)
        event = Event.objects.create(makerspace=tenant, title="Workshop", starts_at=start,
            ends_at=start + timedelta(hours=1), status="published")
        EventRegistration.objects.create(event=event, member=borrower, name="Borrower", email=borrower.email,
            status="pending_approval")
        room = BookableSpace.objects.create(makerspace=tenant, name="Room")
        for status in ["pending", "confirmed"]:
            Booking.objects.create(space=room, member=borrower, name="Borrower", email=borrower.email, phone=borrower.phone,
                starts_at=start, ends_at=start + timedelta(hours=1), status=status)
    counts = build_dashboard(space)
    assert counts["upcoming_events"] == int(family == "events")
    assert counts["pending_event_registrations"] == int(family == "events")
    assert counts["pending_bookings"] == int(family == "bookings")
    assert counts["upcoming_bookings"] == int(family == "bookings")
    assert counts["low_stock"] == int(family == "inventory")
    assert counts["pending_prints"] == 0
    assert counts["stocktakes_awaiting_approval"] == 0
    assert InventoryProduct.objects.filter(makerspace=space).exists()


def test_event_only_custom_role_gets_its_dashboard_and_cannot_read_another_tenant():
    space, other = family_space("dashboard-event-role", "events"), family_space("dashboard-event-foreign", "events")
    actor = account("dashboard-event-staff")
    role = MakerspaceRole.objects.create(makerspace=space, name="Event organiser", slug="organiser",
        granted_actions=["manage_events"])
    MakerspaceMembership.objects.create(makerspace=space, user=actor, assigned_role=role, role="custom", status="active")
    api = client(actor)
    own = api.get(f"/api/v1/admin/makerspace/{space.pk}/dashboard")
    assert own.status_code == 200, own.data
    assert own.data["upcoming_events"] == 0
    assert api.get(f"/api/v1/admin/makerspace/{other.pk}/dashboard").status_code == 404


def test_aggregation_failure_is_logged_and_dashboard_stays_available(monkeypatch, caplog):
    space = family_space("dashboard-logged-failure", loans=True)

    def unavailable(*args, **kwargs):
        raise RuntimeError("private-contact@example.test secret-provider-token")

    monkeypatch.setattr(InventoryProduct.objects, "filter", unavailable)
    counts = build_dashboard(space)
    assert counts["low_stock"] == 0
    assert any(record.makerspace_id == space.pk for record in caplog.records if hasattr(record, "makerspace_id"))
    assert "private-contact" not in caplog.text and "secret-provider-token" not in caplog.text


@pytest.mark.parametrize("family", ["events", "bookings"])
def test_machine_and_programme_role_keeps_its_programme_counters(family):
    space = family_space(f"dashboard-machine-{family}", "machines", family)
    actor = account(f"dashboard-machine-{family}-staff")
    role = MakerspaceRole.objects.create(makerspace=space, name="Mixed staff", slug="mixed",
        granted_actions=["manage_machines", f"manage_{family}"])
    MakerspaceMembership.objects.create(makerspace=space, user=actor, assigned_role=role, role="custom", status="active")
    start = timezone.now() + timedelta(days=1)
    if family == "events":
        Event.objects.create(makerspace=space, title="Workshop", starts_at=start,
            ends_at=start + timedelta(hours=1), status="published")
    else:
        room = BookableSpace.objects.create(makerspace=space, name="Room")
        Booking.objects.create(space=room, member=actor, name=actor.display_name,
            email=actor.email, phone=actor.phone, starts_at=start,
            ends_at=start + timedelta(hours=1), status="confirmed")
    result = client(actor).get(f"/api/v1/admin/makerspace/{space.pk}/dashboard")
    assert result.status_code == 200, result.data
    assert result.data["scope_mode"] == "full"
    assert result.data[f"upcoming_{family}"] == 1


def test_dashboard_row_queries_apply_actor_tenant_scope():
    space = family_space("dashboard-no-actor-scope", loans=True)
    InventoryProduct.objects.create(makerspace=space, name="Private shelf", available_quantity=0)
    assert build_dashboard(space, actor=account("dashboard-outsider"))["low_stock"] == 0


def test_event_counter_failure_does_not_suppress_booking_counts(monkeypatch, caplog):
    space = family_space("dashboard-programme-failure", "events", "bookings")
    room = BookableSpace.objects.create(makerspace=space, name="Room")
    start = timezone.now() + timedelta(days=1)
    Booking.objects.create(space=room, starts_at=start, ends_at=start + timedelta(hours=1),
        name="Visitor", email="visitor@example.test", phone="1", status="pending")

    def unavailable(*args, **kwargs):
        raise RuntimeError("private-contact@example.test")

    monkeypatch.setattr(Event.objects, "filter", unavailable)
    counts = build_dashboard(space)
    assert counts["upcoming_events"] == 0 and counts["pending_bookings"] == 1
    assert "Dashboard programme aggregation failed" in caplog.text
    assert "private-contact" not in caplog.text


def test_read_only_inventory_staff_cannot_query_manager_email_counters(monkeypatch):
    from apps.integrations.models import EmailLog

    space = family_space("dashboard-email-authority", "email", loans=True)
    actor = account("dashboard-inventory-reader")
    role = MakerspaceRole.objects.create(makerspace=space, name="Reader", slug="reader", granted_actions=["view_inventory"])
    MakerspaceMembership.objects.create(makerspace=space, user=actor, assigned_role=role, role="custom", status="active")

    def forbidden(*args, **kwargs):
        pytest.fail("Inventory read authority queried manager-only email logs")

    monkeypatch.setattr(EmailLog.objects, "filter", forbidden)
    result = client(actor).get(f"/api/v1/admin/makerspace/{space.pk}/dashboard")
    assert result.status_code == 200 and result.data["failed_emails"] == 0


@pytest.mark.parametrize("machine_grant", [False, True])
def test_finance_role_sees_core_pending_debt_without_an_online_rail(machine_grant):
    from apps.payments.models import Payment

    space = family_space("dashboard-finance-only", "membership", "machines")
    actor = account("dashboard-finance-staff")
    actions = ["view_finance", *(["manage_machines"] if machine_grant else [])]
    role = MakerspaceRole.objects.create(makerspace=space, name="Finance", slug="finance", granted_actions=actions)
    membership = MakerspaceMembership.objects.create(makerspace=space, user=actor, assigned_role=role, role="custom", status="active")
    Payment.objects.create(makerspace=space, member=actor, created_by=actor, subject_type="makerspace_membership",
        subject_id=membership.pk, amount="15.00", currency="usd", provider="unclaimed")
    result = client(actor).get(f"/api/v1/admin/makerspace/{space.pk}/dashboard")
    assert result.status_code == 200, result.data
    assert result.data["pending_payments"] == 1 and result.data["outstanding_by_currency"] == {"usd": "15.00"}
    assert "payments" not in space.enabled_modules


def test_event_staff_does_not_gain_hardware_counts_on_a_mixed_tenant():
    space = family_space("dashboard-event-mixed", "events", "machines", loans=True)
    InventoryProduct.objects.create(makerspace=space, name="Private empty shelf", available_quantity=0)
    actor = account("dashboard-mixed-event-staff")
    role = MakerspaceRole.objects.create(makerspace=space, name="Event organiser", slug="organiser", granted_actions=["manage_events"])
    MakerspaceMembership.objects.create(makerspace=space, user=actor, assigned_role=role, role="custom", status="active")
    result = client(actor).get(f"/api/v1/admin/makerspace/{space.pk}/dashboard")
    assert result.status_code == 200 and result.data["low_stock"] == 0


def test_disabled_loans_do_not_query_inventory_counters(monkeypatch):
    space = family_space("dashboard-no-loan-query", "events")

    def forbidden(*args, **kwargs):
        pytest.fail("Disabled loans queried inventory")

    monkeypatch.setattr(InventoryProduct.objects, "filter", forbidden)
    assert build_dashboard(space)["low_stock"] == 0
