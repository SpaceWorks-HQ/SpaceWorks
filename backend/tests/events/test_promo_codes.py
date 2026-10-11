from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.events import services
from apps.events.promos import create_promo, revoke_promo
from apps.events.ticketing import create_ticket
from apps.payments.models import Payment
from tests.events.collab_helpers import make_staff, client_for
from tests.events.ticketing_helpers import event_space, account, open_event, signup

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("discount,expected", [({"percent_off": 20}, "20"), ({"amount_off": 4}, "21"), ({"amount_off": 50}, "0")])
def test_promo_modifies_real_charge_and_audits_once(discount, expected):
    space = event_space()
    event, user = open_event(space), account()
    staff = make_staff(space)
    ticket = create_ticket(event, actor=staff, name="Paid", amount=25)
    promo, code = create_promo(event, actor=staff, **discount)
    assert code not in str(promo.__dict__)
    assert signup(event, user, ticket_type_id=ticket.pk, promo_code=code).status_code == 201
    registration = event.registrations.get()
    assert registration.quoted_amount == Decimal(expected)
    if Decimal(expected):
        payment = Payment.objects.get(subject_id=registration.pk, subject_type="event_registration")
        assert payment.amount == Decimal(expected) and payment.provider == "unclaimed"
    else:
        assert not Payment.objects.exists()
    assert signup(event, user, ticket_type_id=ticket.pk, promo_code=code).status_code == 201
    promo.refresh_from_db()
    assert promo.uses == 1
    assert AuditLog.objects.filter(action="event.promo_redeemed", actor=user).count() == 1
    assert code not in str(list(AuditLog.objects.values_list("meta", flat=True)))


@pytest.mark.parametrize("state", ["expired", "revoked", "used", "foreign", "unknown"])
def test_promo_limits_and_scoping_are_uniform_and_atomic(state):
    space = event_space()
    staff = make_staff(space)
    event = open_event(space)
    ticket = create_ticket(event, actor=staff, name="Paid", amount=10)
    promo, code = create_promo(event, actor=staff, percent_off=10)
    if state == "expired":
        promo.expires_at = timezone.now() - timedelta(seconds=1)
        promo.save(update_fields=["expires_at"])
    elif state == "revoked":
        revoke_promo(promo, actor=staff)
    elif state == "used":
        assert signup(event, account("first"), ticket_type_id=ticket.pk, promo_code=code).status_code == 201
    elif state == "foreign":
        event = open_event(event_space("foreign"))
        ticket = create_ticket(event, actor=None, name="Paid", amount=10)
    elif state == "unknown":
        code = "unknown"
    user = account()
    assert signup(event, user, ticket_type_id=ticket.pk, promo_code=code).status_code == 404
    assert not event.registrations.filter(member=user).exists()


def test_waitlisted_discount_survives_expiry_and_is_used_on_charge_creation():
    space = event_space()
    staff, first, waiter = make_staff(space), account("first"), account("waiter")
    event = open_event(space, capacity=1)
    ticket = create_ticket(event, actor=staff, name="Paid", amount=10)
    promo, code = create_promo(event, actor=staff, percent_off=50)
    signup(event, first, ticket_type_id=ticket.pk)
    signup(event, waiter, ticket_type_id=ticket.pk, promo_code=code)
    promo.expires_at = timezone.now() - timedelta(seconds=1)
    promo.save(update_fields=["expires_at"])
    services.cancel_registration(event.registrations.get(member=first), actor=staff)
    reg = event.registrations.get(member=waiter)
    assert reg.status == "registered"
    assert Payment.objects.get(subject_id=reg.pk, subject_type="event_registration").amount == Decimal("5")


def test_promo_redemption_is_bounded_by_registration_throttle(monkeypatch):
    from apps.apiclients.throttling import ClientTierRateThrottle
    monkeypatch.setattr(ClientTierRateThrottle, "get_rate", lambda self: "2/min")
    space = event_space()
    event = open_event(space)
    user = account()
    ticket = create_ticket(event, actor=make_staff(space), name="Paid", amount=10)
    cache.clear()
    responses = [signup(event, user, ticket_type_id=ticket.pk, promo_code="invalid") for _ in range(3)]
    assert any(row.status_code == 429 for row in responses)
    assert not event.registrations.exists()


def test_staff_promo_create_list_and_revoke_hide_secret_and_cross_tenant():
    space, other = event_space(), event_space("other")
    staff, foreign = make_staff(space), make_staff(other)
    event = open_event(space)
    path = reverse("admin-event-promos", args=[event.pk])
    assert client_for(foreign).post(path, {"percent_off": 20}, format="json").status_code == 404
    response = client_for(staff).post(path, {"percent_off": 20}, format="json")
    assert response.status_code == 201
    assert "code" not in client_for(staff).get(path).data["results"][0]
    assert client_for(staff).post(reverse("admin-event-promo-revoke", args=[response.data["id"]]), {}, format="json").status_code == 200


def test_named_promo_can_be_reused_on_another_event_but_not_duplicated_here():
    from rest_framework.exceptions import ValidationError
    space = event_space()
    staff = make_staff(space)
    first, second = open_event(space), open_event(space)
    create_promo(first, actor=staff, code="WELCOME2026", percent_off=10)
    create_promo(second, actor=staff, code="WELCOME2026", percent_off=20)
    with pytest.raises(ValidationError):
        create_promo(first, actor=staff, code="welcome2026", percent_off=10)
