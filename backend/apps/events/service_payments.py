"""Event charging boundary; payment failures never affect registration."""

from django.db import IntegrityError, transaction

from apps.payments.availability import online_payments_enabled
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.reconciliation import cancel_pending
from apps.payments.services import create_checkout, create_payment


def create_for_registered_registration(registration, actor):
    try:
        event = registration.event
        member = registration.member
        if (
            member is None
            or event.payment_amount <= 0
            or not online_payments_enabled(event.makerspace, "events")
        ):
            return None
        payment = _get_or_create(registration, actor or member)
        if payment.status == Payment.Status.PENDING:
            _schedule_checkout(payment)
        return payment
    except Exception:
        return None


def _get_or_create(registration, created_by):
    event = registration.event
    lookup = {
        "makerspace": event.makerspace,
        "subject_type": Payment.SubjectType.EVENT_REGISTRATION,
        "subject_id": registration.pk,
    }
    existing = Payment.objects.filter(**lookup).first()
    if existing is not None:
        return existing
    currency = MakerspacePaymentSettings.for_makerspace(
        event.makerspace
    ).default_currency
    try:
        with transaction.atomic():
            # Routing is stamped now because a purge may later clear the registration's
            # provenance. `payment_via_makerspace` is read FIRST and is the whole point of
            # that column: a waitlisted registration reaches this line only at promotion,
            # potentially after the collaborator purged `events` and nulled the provenance,
            # and falling back to the host would route the charge to a space the visiting
            # member cannot reach.
            return create_payment(
                **lookup,
                member=registration.member,
                via_makerspace=(
                    registration.payment_via_makerspace
                    or registration.registered_via_makerspace
                    or event.makerspace
                ),
                amount=event.payment_amount,
                currency=currency,
                created_by=created_by,
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


def cancel_for_registration(registration, actor):
    try:
        return cancel_pending(
            makerspace=registration.event.makerspace,
            subject_type=Payment.SubjectType.EVENT_REGISTRATION,
            subject_id=registration.pk,
            actor=actor,
        )
    except Exception:
        return None
