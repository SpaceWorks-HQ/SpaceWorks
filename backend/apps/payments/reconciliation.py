"""Transactional reconciliation for every payment subject type."""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework.exceptions import APIException, NotFound

from apps.accounts import rbac
from apps.audit import services as audit
from apps.payments.models import Payment

# Re-export barrel: these moved to submodules at the 300-line ceiling, but
# `from apps.payments.reconciliation import X` must keep resolving for every caller.
from apps.payments.reconciliation_authority import (  # noqa: F401
    SUBJECT_ACTIONS,
    _require_machine_scope,
    _require_subject_authority,
)
from apps.payments.reconciliation_rail import _expire_checkout_best_effort  # noqa: F401

logger = logging.getLogger(__name__)


class PaymentConflict(APIException):
    status_code = 409

    def __init__(self, payment_ids):
        self.detail = {
            "detail": "Only pending payments can be reconciled.",
            "code": "payment_terminal",
            "payment_ids": list(payment_ids),
        }


def list_payments(*, actor, makerspace_id, status=None, subject_type=None):
    queryset = rbac.scope_by_action(
        actor,
        rbac.Action.MANAGE_MAKERSPACE,
        Payment.objects.select_related("makerspace"),
        field="makerspace_id",
    ).filter(makerspace_id=makerspace_id)
    if status:
        queryset = queryset.filter(status=status)
    if subject_type:
        queryset = queryset.filter(subject_type=subject_type)
    return with_refunds(queryset).order_by("-created_at", "-pk")


def with_refunds(queryset):
    """Annotate the money actually sent back and prefetch the refund lines."""
    from apps.payments.models import Refund

    return queryset.prefetch_related("refunds").annotate(
        refunded_amount=Coalesce(
            Sum("refunds__amount", filter=Q(refunds__status=Refund.Status.SUCCEEDED)),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )


def mark_offline(payment, actor):
    return _compat_reconcile(
        actor=actor,
        payment=payment,
        target_status=Payment.Status.PAID_OFFLINE,
    )


def waive(payment, actor):
    return _compat_reconcile(
        actor=actor,
        payment=payment,
        target_status=Payment.Status.WAIVED,
    )


@transaction.atomic
def cancel_pending(*, makerspace, subject_type, subject_id, actor):
    """Cancel a subject's pending charge without affecting its domain workflow."""
    payment = (
        Payment.objects.select_for_update()
        .filter(
            makerspace=makerspace,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        .first()
    )
    if payment is None or payment.status != Payment.Status.PENDING:
        return payment
    _expire_checkout_best_effort(payment)
    payment.status = Payment.Status.CANCELED
    payment.save(
        update_fields=[
            "status",
            "stripe_checkout_session_expired_at",
            "updated_at",
        ]
    )
    audit.record(
        actor,
        "payment.canceled",
        makerspace=makerspace,
        target=payment,
    )
    return payment


def _compat_reconcile(*, payment, actor, target_status):
    current = Payment.objects.get(pk=payment.pk)
    if current.status != Payment.Status.PENDING:
        return current
    return reconcile_payments(
        actor=actor,
        makerspace_id=current.makerspace_id,
        payment_ids=[current.pk],
        target_status=target_status,
    )[0]


@transaction.atomic
def reconcile_payments(
    *, actor, makerspace_id, payment_ids, target_status, settlement=None
):
    """Lock, validate, then reconcile a batch without partial mutations.

    `settlement` is the manual receipt -- method, reference, received_at -- recorded for
    a PAID_OFFLINE batch. It is written in the same transaction as the status flip, so a
    settled charge can never exist without the cash-book row that explains it. Waiving
    takes no settlement: no money changed hands.
    """
    if target_status not in {Payment.Status.PAID_OFFLINE, Payment.Status.WAIVED}:
        raise ValueError("Unsupported reconciliation status.")
    if settlement and target_status != Payment.Status.PAID_OFFLINE:
        raise ValueError("Only an offline settlement carries receipt details.")

    requested_ids = list(payment_ids)
    locked = list(
        Payment.objects.select_for_update()
        .select_related("makerspace")
        .filter(makerspace_id=makerspace_id, pk__in=requested_ids)
        .order_by("pk")
    )
    by_id = {payment.pk: payment for payment in locked}
    if len(by_id) != len(requested_ids):
        raise NotFound("Payment not found.")

    _require_subject_authority(actor, locked)
    terminal_ids = [payment.pk for payment in locked if payment.status != Payment.Status.PENDING]
    if terminal_ids:
        raise PaymentConflict(terminal_ids)

    action = (
        "payment.paid_offline"
        if target_status == Payment.Status.PAID_OFFLINE
        else "payment.waived"
    )
    for payment in locked:
        _expire_checkout_best_effort(payment)
        payment.status = target_status
        payment.save(
            update_fields=[
                "status",
                "stripe_checkout_session_expired_at",
                "updated_at",
            ]
        )
        meta = None
        if settlement and target_status == Payment.Status.PAID_OFFLINE:
            receipt = _record_settlement(payment, actor, settlement)
            meta = {"method": receipt.method, "settlement_id": receipt.pk}
        audit.record(
            actor, action, makerspace=payment.makerspace, target=payment, meta=meta
        )
    return [by_id[payment_id] for payment_id in requested_ids]


def _record_settlement(payment, actor, settlement):
    """Append the cash-book row for one settled charge.

    Amount and currency are taken from the PAYMENT, never from the caller: the receipt
    describes the debt that was settled, and letting a client name its own figure would
    let the books disagree with the ledger they are supposed to explain.
    """
    from apps.payments.models import ManualSettlement

    return ManualSettlement.objects.create(
        payment=payment,
        method=settlement["method"],
        reference=settlement.get("reference", ""),
        received_at=settlement["received_at"],
        amount=payment.amount,
        currency=payment.currency,
        recorded_by=actor,
    )
