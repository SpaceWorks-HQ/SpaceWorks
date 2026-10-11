from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.events import services, services_series
from apps.events.models import EventTicketType
from apps.events.ticketing import create_ticket
from apps.payments.models import Payment
from tests.events.collab_helpers import make_staff, make_member, client_for
from tests.events.ticketing_helpers import event_space, account, open_event, signup, public_url

pytestmark = pytest.mark.django_db


def test_member_price_public_price_and_membership_off_degrade():
    space = event_space(membership=True)
    event = open_event(space)
    staff, member, public = make_staff(space), make_member(space), account()
    member_type = create_ticket(event, actor=staff, name="Member", audience="member", amount=5)
    public_type = create_ticket(event, actor=staff, name="Public", audience="public", amount=25)
    assert signup(event, public, ticket_type_id=member_type.pk).status_code == 404
    assert signup(event, member, ticket_type_id=member_type.pk).status_code == 201
    assert signup(event, public, ticket_type_id=public_type.pk).status_code == 201
    assert set(Payment.objects.values_list("amount", flat=True)) == {Decimal("5"), Decimal("25")}
    space.enabled_modules.remove("membership")
    space.save(update_fields=["enabled_modules"])
    detail = client_for(member).get(public_url(event, "public-event-detail"))
    assert [row["id"] for row in detail.data["ticket_types"]] == [public_type.pk]
    assert signup(event, account("late"), ticket_type_id=member_type.pk).status_code == 404


def test_per_type_capacity_fifo_and_price_snapshot_survive_promotion():
    space = event_space()
    event = open_event(space, capacity=0)
    staff = make_staff(space)
    ticket = create_ticket(event, actor=staff, name="Limited", capacity=1, amount=10)
    first, waiter = account("first"), account("waiter")
    assert signup(event, first, ticket_type_id=ticket.pk).data["status"] == "registered"
    assert signup(event, waiter, ticket_type_id=ticket.pk).data["status"] == "waitlisted"
    ticket.amount = 99
    ticket.save(update_fields=["amount"])
    confirmed = event.registrations.get(member=first)
    waiting = event.registrations.get(member=waiter)
    assert not Payment.objects.filter(subject_id=waiting.pk).exists()
    services.cancel_registration(confirmed, actor=staff)
    waiting.refresh_from_db()
    assert waiting.status == "registered"
    charge = Payment.objects.get(subject_id=waiting.pk, subject_type="event_registration")
    assert charge.amount == Decimal("10") and charge.provider == "unclaimed"


def test_promotion_skips_a_full_type_and_respects_event_capacity():
    space = event_space()
    event = open_event(space, capacity=2)
    staff = make_staff(space)
    one = create_ticket(event, actor=staff, name="One", capacity=1)
    two = create_ticket(event, actor=staff, name="Two", capacity=1)
    users = [account(f"user{i}") for i in range(4)]
    for user, ticket in zip(users, [one, one, two, two]):
        signup(event, user, ticket_type_id=ticket.pk)
    services.cancel_registration(event.registrations.get(member=users[2]), actor=staff)
    assert event.registrations.get(member=users[1]).status == "waitlisted"
    assert event.registrations.get(member=users[3]).status == "registered"


@pytest.mark.parametrize("window", ["future", "past"])
def test_sales_window_hides_and_refuses_type(window):
    space = event_space()
    event = open_event(space)
    values = {"sales_start_at": timezone.now() + timedelta(days=1)} if window == "future" else {"sales_end_at": timezone.now() - timedelta(seconds=1)}
    ticket = create_ticket(event, actor=make_staff(space), name="Window", **values)
    assert signup(event, account(), ticket_type_id=ticket.pk).status_code == 404


def test_series_materialization_copies_independent_ticket_templates():
    space = event_space()
    staff = make_staff(space)
    series, occurrences = services_series.create_series(
        makerspace=space, actor=staff, title="Series", description="", location="",
        registration_audience="accounts", recurrence_timezone="UTC",
        dtstart_local_date=(timezone.now() + timedelta(days=1)).date(), dtstart_local_time=time(10),
        recurrence_rule="FREQ=DAILY;COUNT=2", duration_minutes=60,
        ticket_types=[{"name": "Public", "amount": Decimal("15"), "capacity": 3}],
    )
    assert len(occurrences) == 2
    template = series.ticket_types.get()
    for event in occurrences:
        ticket = event.ticket_types.get()
        assert ticket.pk != template.pk and ticket.amount == template.amount and ticket.capacity == 3
        assert ticket.series_id is None and event.registration_audience == "accounts"


def test_idempotent_registration_retry_survives_closed_ticket_sales():
    space = event_space()
    event = open_event(space)
    ticket = create_ticket(event, actor=make_staff(space), name="Paid", amount=10)
    user = account()
    assert signup(event, user, ticket_type_id=ticket.pk).status_code == 201
    ticket.sales_end_at = timezone.now() - timedelta(seconds=1)
    ticket.save(update_fields=["sales_end_at"])
    assert signup(event, user, ticket_type_id=ticket.pk).status_code == 201
    assert event.registrations.count() == 1
    assert Payment.objects.filter(subject_type="event_registration").count() == 1


def test_membership_off_with_only_member_types_cannot_fall_back_to_free():
    space = event_space()
    event = open_event(space)
    ticket = create_ticket(event, actor=make_staff(space), name="Members", audience="member", amount=10)
    user = account()
    detail = client_for(user).get(public_url(event, "public-event-detail"))
    assert detail.data["ticket_types"] == [] and detail.data["ticket_selection_required"] is True
    assert signup(event, user).status_code == 400
    assert signup(event, user, ticket_type_id=ticket.pk).status_code == 404
    assert not event.registrations.exists()


def test_ledger_failure_rolls_back_paid_registration_and_code_redemption(monkeypatch):
    from apps.events import service_payments
    from apps.events.promos import create_promo
    space = event_space()
    staff, user = make_staff(space), account()
    event = open_event(space)
    ticket = create_ticket(event, actor=staff, name="Paid", amount=10)
    promo, code = create_promo(event, actor=staff, percent_off=50)
    def unavailable(*args, **kwargs):
        raise RuntimeError("local ledger unavailable")
    monkeypatch.setattr(service_payments, "_get_or_create", unavailable)
    with pytest.raises(RuntimeError, match="local ledger unavailable"):
        services.register(event, member=user, actor=user, ticket_type_id=ticket.pk, promo_code=code)
    assert not event.registrations.exists()
    promo.refresh_from_db()
    assert promo.uses == 0


def test_optional_checkout_failure_keeps_the_recorded_charge(monkeypatch):
    from apps.events import service_payments
    space = event_space()
    staff, user = make_staff(space), account()
    event = open_event(space)
    ticket = create_ticket(event, actor=staff, name="Paid", amount=10)
    monkeypatch.setattr(service_payments, "online_payments_enabled", lambda *args: True)
    def unavailable(*args):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(service_payments, "_schedule_checkout", unavailable)
    assert signup(event, user, ticket_type_id=ticket.pk).status_code == 201
    assert Payment.objects.get(subject_id=event.registrations.get().pk, subject_type="event_registration").amount == 10


def test_approval_uses_frozen_discount_and_type_capacity():
    from apps.events.promos import create_promo
    space = event_space()
    staff = make_staff(space)
    event = open_event(space, registration_requires_approval=True)
    ticket = create_ticket(event, actor=staff, name="Public", amount=10, capacity=1)
    promo, code = create_promo(event, actor=staff, percent_off=50, max_uses=2)
    first, second = account("first"), account("second")
    for user in (first, second):
        assert signup(event, user, ticket_type_id=ticket.pk, promo_code=code).data["status"] == "pending_approval"
    assert not Payment.objects.filter(subject_type="event_registration").exists()
    ticket.amount = 99
    ticket.save(update_fields=["amount"])
    services.approve_registration(event.registrations.get(member=first), actor=staff)
    services.approve_registration(event.registrations.get(member=second), actor=staff)
    assert event.registrations.get(member=second).status == "waitlisted"
    assert Payment.objects.get(subject_type="event_registration").amount == 5
