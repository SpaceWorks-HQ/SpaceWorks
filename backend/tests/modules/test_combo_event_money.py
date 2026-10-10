"""events x charge tracking: cancelling an event closes its open charges (matrix E8).

A cancelled event revoked certificates and closed its survey but left every PENDING
registration charge open, so members kept owing money for an event that will not
happen -- and, with the online rail on, kept a live payment link for it.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.events import services as event_services
from apps.events.models import Event, EventRegistration
from apps.payments.models import Payment
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db


def _paid_event(space, title="Paid workshop", **extra):
    start = timezone.now() + timedelta(days=2)
    return Event.objects.create(
        makerspace=space, title=title, starts_at=start, ends_at=start + timedelta(hours=2),
        is_public=True, status=Event.Status.PUBLISHED, payment_amount="12.00", **extra,
    )


def _member(slug, space):
    user = make_member(slug, space)
    user.phone = "1"
    user.save(update_fields=["phone"])
    return user


def test_cancelling_an_event_cancels_pending_charges_and_keeps_settled_ones(
    django_capture_on_commit_callbacks,
):
    space = make_space("combo-event-cancel")
    manager = _member("combo-event-cancel-manager", space)
    payer, settled_payer = _member("combo-event-payer", space), _member("combo-event-paid", space)
    event = _paid_event(space)
    pending = event_services.register(event, member=payer, actor=payer)
    settled = event_services.register(event, member=settled_payer, actor=settled_payer)
    charge = Payment.objects.get(subject_id=pending.pk, subject_type="event_registration")
    assert charge.status == Payment.Status.PENDING
    # A waived (terminal) charge stands in for money that was settled: it must not move.
    Payment.objects.filter(subject_id=settled.pk, subject_type="event_registration").update(
        status=Payment.Status.WAIVED
    )

    with django_capture_on_commit_callbacks(execute=True):
        event_services.cancel(event, actor=manager)

    charge.refresh_from_db()
    assert charge.status == Payment.Status.CANCELED
    assert Payment.objects.get(subject_id=settled.pk).status == Payment.Status.WAIVED
    assert AuditLog.objects.filter(action="payment.canceled", target_id=str(charge.pk)).exists()
    assert EventRegistration.objects.filter(event=event).count() == 2


def test_an_event_with_no_open_charges_cancels_exactly_as_before(django_capture_on_commit_callbacks):
    space = make_space("combo-event-cancel-free")
    manager = _member("combo-event-cancel-free-manager", space)
    event = _paid_event(space, title="Free talk")
    Event.objects.filter(pk=event.pk).update(payment_amount=0)
    event_services.register(event, member=_member("combo-free-attendee", space), actor=manager)

    with django_capture_on_commit_callbacks(execute=True):
        cancelled = event_services.cancel(event, actor=manager)

    assert cancelled.status == Event.Status.CANCELLED
    assert not Payment.objects.exists()
    assert not AuditLog.objects.filter(action="payment.canceled").exists()
