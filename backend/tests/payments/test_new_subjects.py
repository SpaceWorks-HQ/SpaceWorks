from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment, ProcessedStripeEvent
from apps.payments.services import apply_webhook_event
from tests.return_helpers import authenticated_client, make_member, make_space


pytestmark = pytest.mark.django_db


def subjects(makerspace, member):
    now = timezone.now() + timedelta(days=1)
    bookable = BookableSpace.objects.create(
        makerspace=makerspace,
        name="Design studio",
    )
    booking = Booking.objects.create(
        space=bookable,
        member=member,
        name=member.username,
        email=member.email,
        phone="1",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    event = Event.objects.create(
        makerspace=makerspace,
        title="Open workshop",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event,
        member=member,
        name=member.username,
        email=member.email,
        phone="1",
    )
    membership = MakerspaceMembership.objects.get(
        makerspace=makerspace,
        user=member,
    )
    return {
        Payment.SubjectType.BOOKING: booking,
        Payment.SubjectType.EVENT_REGISTRATION: registration,
        Payment.SubjectType.MAKERSPACE_MEMBERSHIP: membership,
    }


def create_payment(makerspace, member, subject_type, subject):
    return Payment.objects.create(
        makerspace=makerspace,
        subject_type=subject_type,
        subject_id=subject.pk,
        member=member,
        amount="8.00",
        currency="usd",
        created_by=member,
    )


def test_member_history_batch_labels_all_new_subjects():
    makerspace = make_space("member-payment-subjects")
    member = make_member("member-payment-subject-user", makerspace)
    rows = subjects(makerspace, member)
    for subject_type, subject in rows.items():
        create_payment(makerspace, member, subject_type, subject)

    response = authenticated_client(member).get(
        f"/api/v1/member/makerspaces/{makerspace.pk}/payments"
    )

    assert response.status_code == 200
    assert {row["subject_label"] for row in response.data} == {
        "Design studio",
        "Open workshop",
        "Membership dues",
    }
    assert all(row["checkout_url"] == "" for row in response.data)


@pytest.mark.parametrize(
    "subject_type",
    [
        Payment.SubjectType.BOOKING,
        Payment.SubjectType.EVENT_REGISTRATION,
        Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
    ],
)
def test_webhook_is_idempotent_for_each_new_subject(subject_type):
    makerspace = make_space(f"new-subject-webhook-{subject_type}")
    member = make_member(f"new-subject-webhook-user-{subject_type}", makerspace)
    subject = subjects(makerspace, member)[subject_type]
    payment = create_payment(makerspace, member, subject_type, subject)
    session_id = f"cs_{subject_type}"
    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_session_id=session_id
    )
    event = {
        "id": f"evt_{subject_type}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "payment_status": "paid",
            }
        },
    }

    assert apply_webhook_event(makerspace, event).status == Payment.Status.PAID_ONLINE
    assert apply_webhook_event(makerspace, event) is None
    assert ProcessedStripeEvent.objects.filter(
        makerspace=makerspace,
        stripe_event_id=event["id"],
    ).count() == 1


@pytest.mark.parametrize(
    "subject_type",
    [
        Payment.SubjectType.BOOKING,
        Payment.SubjectType.EVENT_REGISTRATION,
        Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
    ],
)
def test_webhook_corrects_waived_new_subject_after_payment(subject_type):
    makerspace = make_space(f"terminal-new-subject-{subject_type}")
    member = make_member(f"terminal-new-subject-user-{subject_type}", makerspace)
    subject = subjects(makerspace, member)[subject_type]
    payment = create_payment(makerspace, member, subject_type, subject)
    session_id = f"cs_terminal_{subject_type}"
    Payment.objects.filter(pk=payment.pk).update(
        status=Payment.Status.WAIVED,
        stripe_checkout_session_id=session_id,
    )
    event_id = f"evt_terminal_{subject_type}"

    result = apply_webhook_event(
        makerspace,
        {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {"object": {"id": session_id, "payment_status": "paid"}},
        },
    )

    result.refresh_from_db()
    assert result.status == Payment.Status.PAID_ONLINE
    anomaly = AuditLog.objects.get(
        action="payment.paid_after_terminal",
        target_id=str(payment.pk),
    )
    assert anomaly.meta["prior_status"] == Payment.Status.WAIVED
    assert anomaly.meta["resolved_status"] == Payment.Status.PAID_ONLINE
