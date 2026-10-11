"""Boundary regressions found during the w7 review, exercised through real workflows."""

from datetime import time, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.events import service_payments, services, services_series
from apps.events.models import EventInvite, EventPromoCode, EventTicketType
from apps.events.ticketing import create_ticket
from apps.payments.models import Payment
from tests.events.collab_helpers import client_for, make_member, make_staff
from tests.events.ticketing_helpers import account, event_space, open_event, public_url, signup

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("cancelled", [False, True])
def test_contact_fallback_cannot_read_or_claim_another_accounts_registration(cancelled):
    space = event_space()
    event = open_event(space)
    owner, caller = account("owner"), account("caller")
    assert signup(event, owner).status_code == 201
    original = event.registrations.get()
    if cancelled:
        services.cancel_registration(original, actor=owner)
    caller.email = ""
    caller.save(update_fields=["email"])
    result = signup(event, caller, email=owner.email)
    assert result.status_code == 400 and "email" in result.data
    assert "status" not in result.data
    original.refresh_from_db()
    assert original.member_id == owner.pk
    assert original.status == ("cancelled" if cancelled else "registered")
    assert not event.registrations.filter(member=caller).exists()


@pytest.mark.parametrize("model", [EventInvite, EventPromoCode, EventTicketType])
def test_ticketing_models_refuse_a_foreign_makerspace_owner(model):
    space, foreign = event_space(), event_space("foreign")
    row = model(makerspace=foreign, event=open_event(space))
    with pytest.raises(ValidationError, match="makerspace"):
        row.clean()


def test_ticket_template_refuses_foreign_series_and_ambiguous_owner():
    space, foreign = event_space(), event_space("foreign")
    series, _ = services_series.create_series(
        makerspace=space, actor=make_staff(space), title="Series", description="", location="",
        registration_audience="accounts", recurrence_timezone="UTC",
        dtstart_local_date=(timezone.now() + timedelta(days=1)).date(), dtstart_local_time=time(10),
        recurrence_rule="FREQ=DAILY;COUNT=1", duration_minutes=60,
    )
    row = EventTicketType(makerspace=foreign, series=series)
    with pytest.raises(ValidationError, match="makerspace"):
        row.clean()
    row.makerspace = space
    row.event = open_event(space)
    with pytest.raises(ValidationError, match="exactly one"):
        row.clean()


def test_revoked_membership_hides_and_refuses_member_prices():
    space = event_space(membership=True)
    staff, member = make_staff(space), make_member(space)
    event = open_event(space)
    member_type = create_ticket(event, actor=staff, name="Member", audience="member", amount=5)
    public_type = create_ticket(event, actor=staff, name="Public", amount=20)
    member.makerspace_memberships.filter(makerspace=space).update(status="revoked")
    response = client_for(member).get(public_url(event, "public-event-detail"))
    assert response.status_code == 200
    assert [row["id"] for row in response.data["ticket_types"]] == [public_type.pk]
    assert signup(event, member, ticket_type_id=member_type.pk).status_code == 404
    assert not event.registrations.exists()


def test_each_materialized_ticket_has_its_own_audit_row():
    space = event_space()
    staff = make_staff(space)
    _, occurrences = services_series.create_series(
        makerspace=space, actor=staff, title="Series", description="", location="",
        registration_audience="accounts", recurrence_timezone="UTC",
        dtstart_local_date=(timezone.now() + timedelta(days=1)).date(), dtstart_local_time=time(10),
        recurrence_rule="FREQ=DAILY;COUNT=2", duration_minutes=60,
        ticket_types=[{"name": "Public", "amount": 15}],
    )
    assert len(occurrences) == 2
    for event in occurrences:
        row = event.ticket_types.get()
        assert AuditLog.objects.filter(
            makerspace=space, actor=staff, action="event.ticket_created", target_id=str(row.pk),
        ).count() == 1


@pytest.mark.parametrize("failure", ["schedule", "checkout", "cancel"])
def test_payment_failures_log_only_ids_and_keep_the_recorded_charge(
    failure, monkeypatch, caplog, django_capture_on_commit_callbacks,
):
    space = event_space()
    user, staff = account(), make_staff(space)
    event = open_event(space)
    ticket = create_ticket(event, actor=staff, name="Paid", amount=10)
    secret = "provider-secret-canary-do-not-log"

    def unavailable(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(service_payments, "online_payments_enabled", lambda *args: failure != "cancel")
    monkeypatch.setattr(service_payments, {
        "schedule": "_schedule_checkout", "checkout": "create_checkout", "cancel": "cancel_pending",
    }[failure], unavailable)
    with django_capture_on_commit_callbacks(execute=True):
        assert signup(event, user, ticket_type_id=ticket.pk).status_code == 201
    registration = event.registrations.get()
    payment = Payment.objects.get(subject_id=registration.pk, subject_type="event_registration")
    assert payment.amount == 10
    if failure == "cancel":
        services.cancel_registration(registration, actor=staff)
    records = [row for row in caplog.records if row.name == "apps.events.service_payments"]
    assert records and secret not in caplog.text
    assert all(row.exc_info is None for row in records)
    assert all(hasattr(row, "payment_id") or hasattr(row, "registration_id") for row in records)
