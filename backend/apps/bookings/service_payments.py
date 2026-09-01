"""Booking charging boundary; payment failures never affect confirmation."""

from django.db import IntegrityError, transaction

from apps.payments.availability import online_payments_enabled
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.reconciliation import cancel_pending
from apps.payments.services import create_checkout, create_payment


def create_for_confirmed_booking(booking, actor):
    try:
        space = booking.space
        makerspace = space.makerspace
        member = booking.member
        if (
            member is None
            or space.payment_amount <= 0
            or not online_payments_enabled(makerspace, "bookings")
        ):
            return None
        payment = _get_or_create(booking, actor or member)
        if payment.status == Payment.Status.PENDING:
            _schedule_checkout(payment)
        return payment
    except Exception:
        return None


def _get_or_create(booking, created_by):
    lookup = {
        "makerspace": booking.space.makerspace,
        "subject_type": Payment.SubjectType.BOOKING,
        "subject_id": booking.pk,
    }
    existing = Payment.objects.filter(**lookup).first()
    if existing is not None:
        return existing
    currency = MakerspacePaymentSettings.for_makerspace(
        booking.space.makerspace
    ).default_currency
    try:
        with transaction.atomic():
            return create_payment(
                **lookup,
                member=booking.member,
                amount=booking.space.payment_amount,
                currency=currency,
                created_by=created_by,
                subject_label=booking.space.name,
            )
    except IntegrityError:
        return Payment.objects.get(**lookup)


def _schedule_checkout(payment):
    def create_safely():
        try:
            create_checkout(payment)
        except Exception:
            pass

    transaction.on_commit(create_safely)


def cancel_for_booking(booking, actor):
    try:
        return cancel_pending(
            makerspace=booking.space.makerspace,
            subject_type=Payment.SubjectType.BOOKING,
            subject_id=booking.pk,
            actor=actor,
        )
    except Exception:
        return None
