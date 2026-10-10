"""Record money returned in person without calling or depending on a provider."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.accounts import rbac
from apps.audit import services as audit
from apps.payments.exceptions_refunds import RefundNotAllowed
from apps.payments.models import Payment, Refund
from apps.payments.serializers_refunds_offline import PaymentOfflineRefundSerializer


def offline_refund_queryset(actor):
    """Manual money-out requires RECORD_PAYMENT, including after rail removal."""
    return rbac.scope_by_action(
        actor, rbac.Action.RECORD_PAYMENT, Payment.objects.all(), field="makerspace_id",
    )


@transaction.atomic
def record_offline_refund(payment, *, amount, reason, receipt, actor, release_deposit=False):
    # Validate here as well as at HTTP: direct service callers must supply a receipt.
    payload = PaymentOfflineRefundSerializer(data={
        "amount": amount, "reason": reason, "receipt": receipt,
    })
    payload.is_valid(raise_exception=True)
    data = payload.validated_data
    locked = (
        offline_refund_queryset(actor).select_for_update().select_related("makerspace")
        .filter(pk=payment.pk, makerspace_id=payment.makerspace_id).first()
    )
    if locked is None:
        raise NotFound("Payment not found.")
    if release_deposit:
        from apps.hardware_requests.models import HardwareRequest
        closed = rbac.scope_by_action(
            actor, rbac.Action.RECORD_PAYMENT, HardwareRequest.objects.all(), field="makerspace_id",
        ).filter(pk=locked.subject_id, makerspace_id=locked.makerspace_id,
                 status__in=[HardwareRequest.Status.RETURNED, HardwareRequest.Status.CLOSED_WITH_ISSUE])
        if locked.subject_type != Payment.SubjectType.LOAN_DEPOSIT or not closed.exists():
            raise RefundNotAllowed("A deposit can be released after the loan closes.", "deposit_not_returned")
    if locked.status != Payment.Status.PAID_OFFLINE:
        raise RefundNotAllowed("Only offline-settled payments accept a manual refund.", "refund_not_offline")
    if Refund.counted_total(locked) + data["amount"] > locked.amount:
        raise RefundNotAllowed("Refund exceeds the refundable balance.", "refund_exceeds_balance")
    refund = Refund.objects.create(
        payment=locked, amount=data["amount"], currency=locked.currency,
        status=Refund.Status.SUCCEEDED, provider=Refund.Provider.MANUAL,
        reason=data["reason"], created_by=actor, settled_at=timezone.now(),
        **data["receipt"],
    )
    audit.record(
        actor, "payment.refund_recorded", makerspace=locked.makerspace, target=locked,
        meta={"payment_id": locked.pk, "refund_id": refund.pk, "amount": str(refund.amount),
              "method": refund.method},
    )
    from apps.payments.notifications import notify_payment
    notify_payment(locked, "refund_issued", refund=refund)
    return refund


@transaction.atomic
def amend_offline_refund(payment, *, refund_id, receipt, actor):
    """Correct metadata, not the amount of money actually returned."""
    from apps.payments.serializers_refunds_offline import ManualRefundReceiptSerializer
    payload = ManualRefundReceiptSerializer(data=receipt)
    payload.is_valid(raise_exception=True)
    locked = offline_refund_queryset(actor).select_for_update().filter(
        pk=payment.pk, makerspace_id=payment.makerspace_id,
    ).first()
    if locked is None:
        raise NotFound("Payment not found.")
    previous = rbac.scope_by_action(
        actor, rbac.Action.RECORD_PAYMENT, Refund.objects.all(), field="payment__makerspace_id",
    ).filter(
        pk=refund_id, payment=locked, provider=Refund.Provider.MANUAL, amended_by__isnull=True,
    ).first()
    if previous is None:
        raise NotFound("Effective manual refund not found.")
    replacement = Refund.objects.create(
        payment=locked, amount=previous.amount, currency=previous.currency,
        provider=Refund.Provider.MANUAL, status=Refund.Status.SUCCEEDED,
        reason=previous.reason, created_by=actor, settled_at=previous.settled_at,
        amends=previous, **payload.validated_data,
    )
    audit.record(actor, "payment.refund_amended", makerspace=locked.makerspace, target=locked,
                 meta={"payment_id": locked.pk, "refund_id": replacement.pk,
                       "amends_id": previous.pk, "method": replacement.method})
    return replacement
