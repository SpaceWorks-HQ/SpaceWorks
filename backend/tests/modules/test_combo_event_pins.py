"""Event combinations: membership, money, series capacity and staff contacts.

Each was right in the code with nothing pinning it, so a regression in any one would have
shipped silently.
"""

from datetime import time, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

import pytest

from apps.events import services_series, services_series_lifecycle
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.walk_in_services import create_walk_in_member
from apps.payments.availability import charge_tracking_enabled
from apps.payments.models import Payment
from tests.events.checkin_helpers import client_for, make_event, make_member, make_space, make_staff
from tests.events.checkin_helpers import register as add_registration

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles():
    cache.clear()
    yield
    cache.clear()


def _register_url(space, event):
    return reverse(
        "public-event-register",
        kwargs={"makerspace_slug": space.slug, "public_token": event.public_token},
    )


def test_a_revoked_member_cannot_register():
    """E1: a revoked membership is no membership, for registration as for borrowing."""
    space = make_space("combo-event-revoked")
    event = make_event(space)
    member = make_member(space)
    MakerspaceMembership.objects.filter(makerspace=space, user=member).update(status="revoked")

    response = client_for(member).post(_register_url(space, event), {}, format="json")

    assert response.status_code == 403, response.data
    assert not EventRegistration.objects.filter(event=event).exists()


def test_a_free_event_registers_without_recording_a_charge():
    """E3: `payment_amount = 0` records no debt even with charge tracking on."""
    space = make_space("combo-event-free")
    space.enabled_features = sorted({*space.enabled_features, "charges.enabled", "charges.events"})
    space.save(update_fields=["enabled_features"])
    assert charge_tracking_enabled(space, "events")
    event = make_event(space, payment_amount=0)
    member = make_member(space)

    response = client_for(member).post(_register_url(space, event), {}, format="json")

    assert response.status_code == 201, response.data
    assert not Payment.objects.filter(makerspace=space).exists()
    assert EventRegistration.objects.get(event=event).status == EventRegistration.Status.REGISTERED

    # Prove the real registration path can charge here: otherwise a broken payment
    # seam would make the zero-fee assertion pass for the wrong reason.
    paid_event = make_event(space, title="Paid control", payment_amount=Decimal("12.00"))
    paid = client_for(member).post(_register_url(space, paid_event), {}, format="json")
    assert paid.status_code == 201, paid.data
    registration = EventRegistration.objects.get(event=paid_event, member=member)
    charge = Payment.objects.get(
        makerspace=space, subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
    )
    assert charge.amount == Decimal("12.00")
    assert charge.status == Payment.Status.PENDING


def test_a_pending_approval_registration_cannot_be_checked_in():
    """E9: only REGISTERED rows are check-in-able, so an unapproved applicant is refused."""
    space = make_space("combo-event-pending-checkin")
    event = make_event(space, registration_requires_approval=True)
    registration = add_registration(
        event, make_member(space), status=EventRegistration.Status.PENDING_APPROVAL
    )

    response = client_for(make_staff(space)).post(
        reverse("admin-event-registration-mark-attended", kwargs={"pk": registration.pk}),
        {},
        format="json",
    )

    assert response.status_code == 409, response.data
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.PENDING_APPROVAL


def test_the_member_qr_route_refuses_with_events_uninstalled():
    """E13: the member's own check-in QR is an events surface and is gated like the rest."""
    space = make_space("combo-event-qr-off")
    member = make_member(space)
    registration = add_registration(make_event(space), member)
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])

    response = client_for(member).get(
        reverse("member-event-checkin-qr", kwargs={"makerspace_id": space.pk, "pk": registration.pk})
    )

    assert response.status_code == 400, response.data
    assert "events is disabled" in str(response.data)


def test_series_occurrences_have_independent_capacity_and_registration_charges():
    """E11: filling one occurrence neither fills nor pays for the next one."""
    space = make_space("combo-series-capacity-money")
    space.enabled_features = sorted({*space.enabled_features, "charges.enabled", "charges.events"})
    space.save(update_fields=["enabled_features"])
    staff = make_staff(space)
    series, created = services_series.create_series(
        makerspace=space, actor=staff, title="Paid series", capacity=1,
        payment_amount=Decimal("25.00"), is_public=True,
        recurrence_timezone="UTC",
        dtstart_local_date=(timezone.now() + timedelta(days=1)).date(),
        dtstart_local_time=time(10), recurrence_rule="FREQ=DAILY;COUNT=2",
        duration_minutes=60,
    )
    assert len(created) == 2
    services_series_lifecycle.publish_series(series, actor=staff)
    first, second = Event.objects.filter(series=series).order_by("starts_at")
    member = make_member(space, "series-attendee")
    waiter = make_member(space, "series-waiter")

    for event in (first, second):
        registered = client_for(member).post(_register_url(space, event), {}, format="json")
        waitlisted = client_for(waiter).post(_register_url(space, event), {}, format="json")
        assert registered.status_code == 201, registered.data
        assert registered.data["status"] == EventRegistration.Status.REGISTERED
        assert waitlisted.status_code == 201, waitlisted.data
        assert waitlisted.data["status"] == EventRegistration.Status.WAITLISTED
        assert event.registrations.filter(status=EventRegistration.Status.REGISTERED).count() == 1
        assert event.registrations.filter(status=EventRegistration.Status.WAITLISTED).count() == 1

    registrations = EventRegistration.objects.filter(event__series=series, member=member)
    charges = Payment.objects.filter(
        makerspace=space, subject_type=Payment.SubjectType.EVENT_REGISTRATION,
    )
    assert charges.count() == 2
    assert set(charges.values_list("subject_id", flat=True)) == set(
        registrations.values_list("pk", flat=True)
    )
    assert set(charges.values_list("member_id", "amount", "status")) == {
        (member.pk, Decimal("25.00"), Payment.Status.PENDING),
    }
    assert not charges.filter(member=waiter).exists()


@pytest.mark.parametrize(
    ("account_email", "account_phone"), [("", ""), ("walk-in@example.test", "1234567890")],
)
def test_staff_registration_email_is_a_fallback_and_account_email_wins(account_email, account_phone):
    """E15: counter-entered contacts cannot replace a person's stored email."""
    space = make_space("combo-staff-email")
    staff = make_staff(space)
    membership = create_walk_in_member(
        staff, space, display_name="Walk-in attendee", email=account_email, phone=account_phone,
    )
    attendee = membership.user
    event = make_event(space)
    url = reverse("admin-event-registration-list", args=[event.pk])
    client = client_for(staff)
    if not account_email:
        refused = client.post(url, {"member_id": attendee.pk}, format="json")
        assert refused.status_code == 400, refused.data
        assert "email" in refused.data
        assert "phone" in refused.data
        assert not EventRegistration.objects.filter(event=event).exists()

    response = client.post(
        url, {
            "member_id": attendee.pk, "email": "fallback@example.test", "phone": "+15550199000",
        }, format="json",
    )

    assert response.status_code == 201, response.data
    registration = EventRegistration.objects.get(event=event)
    assert registration.member_id == attendee.pk
    assert registration.email == (account_email or "fallback@example.test")
    assert registration.phone == (account_phone or "+15550199000")
    attendee.refresh_from_db()
    assert attendee.email == account_email
    assert attendee.phone == account_phone
