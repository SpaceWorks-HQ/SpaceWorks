"""Membership-dues boundary; payment failures never affect activation."""

from django.db import IntegrityError, transaction

from apps.payments.availability import online_payments_enabled
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.reconciliation import cancel_pending
from apps.payments.services import create_checkout, create_payment


def create_for_active_membership(membership, actor):
    try:
        makerspace = membership.makerspace
        if (
            makerspace.membership_dues_amount <= 0
            or not online_payments_enabled(makerspace, "membership")
        ):
            return None
        payment = _get_or_create(membership, actor or membership.user)
        if payment.status == Payment.Status.PENDING:
            _schedule_checkout(payment)
        return payment
    except Exception:
        return None


def _get_or_create(membership, actor):
    makerspace = membership.makerspace
    lookup = {
        "makerspace": makerspace,
        "subject_type": Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        "subject_id": membership.pk,
    }
    existing = Payment.objects.filter(**lookup).first()
    if existing is not None:
        return existing
    currency = MakerspacePaymentSettings.for_makerspace(
        makerspace
    ).default_currency
    try:
        with transaction.atomic():
            return create_payment(
                **lookup,
                member=membership.user,
                amount=makerspace.membership_dues_amount,
                currency=currency,
                created_by=actor,
                subject_label="Membership dues",
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


def cancel_for_membership(membership, actor):
    try:
        return cancel_pending(
            makerspace=membership.makerspace,
            subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            subject_id=membership.pk,
            actor=actor,
        )
    except Exception:
        return None
