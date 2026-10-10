"""Member deadlines preserve capacity and historical charges under the event lock."""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.events import services, services_series
from apps.events.cancellation_policy import cancellation_cutoff
from apps.events.exceptions import EventInvalidTransition
from apps.events.models import EventRegistration
from apps.events.serializers_admin import EventAdminSerializer, EventWriteSerializer
from apps.events.serializers_series import EventSeriesDetailSerializer, EventSeriesWriteSerializer
from apps.makerspaces.member_activity_service import _event_registrations
from apps.payments.models import Payment
from tests.events.collab_helpers import (
    client_for, collaborate, make_event, make_member, make_space, make_staff,
)
from tests.events.test_registration_cancel_api import cancel_url, enable_charges, register

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("lead_hours", [None, 0, 2])
@pytest.mark.parametrize("offset_us, expected", [(-1, 200), (0, 409), (1, 409)])
def test_member_cancellation_deadline_is_strict_and_preserves_capacity(
    monkeypatch, lead_hours, offset_us, expected,
):
    space = make_space("member-cancel-cutoff")
    first, waiter = make_member(space), make_member(space, "waiter")
    event = make_event(space)
    event.capacity, event.cancellation_cutoff_hours = 1, lead_hours
    event.save(update_fields=["capacity", "cancellation_cutoff_hours"])
    confirmed, waiting = register(event, first), register(event, waiter)
    now = cancellation_cutoff(event) + timedelta(microseconds=offset_us)
    monkeypatch.setattr("apps.events.cancellation_policy.timezone.now", lambda: now)

    response = client_for(first).post(cancel_url(space, confirmed), {}, format="json")

    assert response.status_code == expected
    confirmed.refresh_from_db()
    waiting.refresh_from_db()
    if expected == 200:
        assert confirmed.status == "cancelled" and waiting.status == "registered"
        assert AuditLog.objects.filter(action="event.registration_cancelled", actor=first).count() == 1
    else:
        assert confirmed.status == "registered" and waiting.status == "waitlisted"
        assert not AuditLog.objects.filter(action="event.registration_cancelled").exists()


def test_member_service_enforces_owner_and_deadline_but_staff_can_override(monkeypatch):
    space = make_space("member-cancel-service")
    member, intruder, staff = make_member(space), make_member(space, "intruder"), make_staff(space)
    event = make_event(space)
    registration = register(event, member)
    with pytest.raises(EventInvalidTransition):
        services.cancel_registration(registration, actor=intruder, member_cancel=True)
    monkeypatch.setattr("apps.events.cancellation_policy.timezone.now", lambda: event.starts_at)
    with pytest.raises(EventInvalidTransition):
        services.cancel_registration(registration, actor=member, member_cancel=True)
    assert services.cancel_registration(registration, actor=staff).status == "cancelled"


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_member_cannot_cancel_registration_for_terminal_event(status):
    space = make_space("member-cancel-terminal-event")
    member = make_member(space)
    event = make_event(space)
    registration = register(event, member)
    event.status = status
    event.save(update_fields=["status"])
    assert client_for(member).post(cancel_url(space, registration), {}, format="json").status_code == 409
    assert not AuditLog.objects.filter(action="event.registration_cancelled").exists()


@pytest.mark.parametrize("tracked, make_free", [(False, False), (True, False), (True, True)])
def test_cancelled_paid_registration_cannot_revive_or_reuse_terminal_charge(tracked, make_free):
    space = make_space("member-cancel-paid-revival")
    if tracked:
        enable_charges(space)
    member = make_member(space)
    event = make_event(space, is_public=True)
    event.payment_amount = Decimal("12")
    event.save(update_fields=["payment_amount"])
    registration = register(event, member)
    services.cancel_registration(registration, actor=member, member_cancel=True)
    if make_free:
        event.payment_amount = Decimal("0")
        event.save(update_fields=["payment_amount"])
    response = client_for(member).post(
        reverse("public-event-register", kwargs={"makerspace_slug": space.slug, "public_token": event.public_token}),
        {"custom_answers": {}}, format="json",
    )
    assert response.status_code == 409
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.CANCELLED
    assert event.registrations.count() == 1
    assert AuditLog.objects.filter(action="event.registration_created").count() == 1
    if tracked:
        assert Payment.objects.get(subject_id=registration.pk, subject_type="event_registration").status == "canceled"


def test_free_cancelled_registration_revives_with_a_new_fifo_position():
    space = make_space("member-cancel-free-revival")
    member, second, third = [make_member(space, name) for name in ("first", "second", "third")]
    event = make_event(space)
    event.capacity = 1
    event.save(update_fields=["capacity"])
    first, middle, last = [register(event, user) for user in (member, second, third)]
    services.cancel_registration(first, actor=member, member_cancel=True)
    revived = register(event, member)
    assert revived.pk == first.pk and revived.status == "waitlisted"
    services.cancel_registration(middle, actor=second, member_cancel=True)
    last.refresh_from_db()
    revived.refresh_from_db()
    assert last.status == "registered" and revived.status == "waitlisted"


def test_member_activity_uses_same_cutoff_for_collaborative_history(monkeypatch):
    host, partner = make_space("cutoff-host"), make_space("cutoff-partner")
    member = make_member(partner)
    event = make_event(host)
    event.cancellation_cutoff_hours = 2
    event.save(update_fields=["cancellation_cutoff_hours"])
    invitation = collaborate(event, partner)
    registration = register(event, member, via_makerspace=partner, collaborative=True)
    invitation.delete()
    now = cancellation_cutoff(event) - timedelta(microseconds=1)
    monkeypatch.setattr("apps.events.cancellation_policy.timezone.now", lambda: now)
    item = _event_registrations(partner, member)[0]
    assert item["registration_id"] == registration.pk
    assert item["can_cancel"] is True and item["cancellation_cutoff_at"] == cancellation_cutoff(event)
    monkeypatch.setattr("apps.events.cancellation_policy.timezone.now", lambda: cancellation_cutoff(event))
    assert _event_registrations(partner, member)[0]["can_cancel"] is False


def test_staff_can_write_cutoff_and_series_occurrences_inherit_with_override():
    space = make_space("cutoff-series")
    staff = make_staff(space)
    series, occurrences = services_series.create_series(
        makerspace=space, actor=staff, title="Safety class", cancellation_cutoff_hours=2,
        recurrence_timezone="UTC", dtstart_local_date=(timezone.now() + timedelta(days=1)).date(),
        dtstart_local_time=time(10), recurrence_rule="FREQ=DAILY;COUNT=2", duration_minutes=60,
    )
    assert len(occurrences) == 2 and all(event.cancellation_cutoff_hours == 2 for event in occurrences)
    services.update_event(occurrences[0], actor=staff, cancellation_cutoff_hours=3)
    services_series.update_series(series, actor=staff, cancellation_cutoff_hours=4)
    occurrences[0].refresh_from_db()
    occurrences[1].refresh_from_db()
    assert occurrences[0].cancellation_cutoff_hours == 3
    assert occurrences[1].cancellation_cutoff_hours == 4
    services.update_event(occurrences[0], actor=staff, inherit_fields=["cancellation_cutoff_hours"])
    occurrences[0].refresh_from_db()
    assert occurrences[0].cancellation_cutoff_hours == 4
    assert EventAdminSerializer(occurrences[0]).data["cancellation_cutoff_hours"] == 4
    series.refresh_from_db()
    assert EventSeriesDetailSerializer(series).data["cancellation_cutoff_hours"] == 4


@pytest.mark.parametrize("serializer_type", [EventWriteSerializer, EventSeriesWriteSerializer])
@pytest.mark.parametrize('hours', [-1, 8761, 2147483647])
def test_negative_or_overflowing_cancellation_hours_rejected_at_api_boundary(serializer_type, hours):
    serializer = serializer_type(data={"cancellation_cutoff_hours": hours}, partial=True)
    assert not serializer.is_valid()
    assert "cancellation_cutoff_hours" in serializer.errors


def test_cancellation_throttle_is_per_member_and_does_not_spend_create_budget(monkeypatch):
    from apps.apiclients.throttling import ClientTierRateThrottle

    monkeypatch.setattr(ClientTierRateThrottle, "get_rate", lambda self: "1/hour")
    space = make_space("cutoff-throttle")
    member = make_member(space)
    event = make_event(space, is_public=True)
    client = client_for(member)
    create_url = reverse("public-event-register", kwargs={
        "makerspace_slug": space.slug, "public_token": event.public_token,
    })
    assert client.post(create_url, {"custom_answers": {}}, format="json").status_code == 201
    registration = EventRegistration.objects.get(event=event, member=member)
    # Registration exhausted the create budget, but must not block releasing a place.
    assert client.post(cancel_url(space, registration), {}, format="json").status_code == 200
    assert client.post(cancel_url(space, registration), {}, format="json").status_code == 429
    other = make_member(space, "other")
    another = register(event, other)
    assert client_for(other).post(cancel_url(space, another), {}, format="json").status_code == 200
