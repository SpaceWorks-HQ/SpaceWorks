"""Record money returned in person without calling or depending on a provider."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.accounts import rbac
from apps.audit import services as audit
from apps.payments.exceptions_refunds import RefundNotAllowed
from apps.payments.models import Payment, Refund
from apps.payments.reconciliation_authority import SUBJECT_ACTIONS, _require_record_authority
from apps.payments.serializers_refunds_offline import PaymentOfflineRefundSerializer


def offline_refund_queryset(actor):
    """One RBAC scope for both endpoint reads and the service's locked query.

    Finance grants cover this makerspace; existing subject grants keep their scope.
    Subject-only machine staff are checked under the payment lock before any refund.
    """
    allowed = rbac.scope_by_action(
        actor, rbac.Action.RECORD_PAYMENT, Payment.objects.all(), field="makerspace_id",
    )
    for subject, action in SUBJECT_ACTIONS.items():
        allowed = allowed | rbac.scope_by_action(
            actor, action, Payment.objects.filter(subject_type=subject), field="makerspace_id",
        )
    return allowed


@transaction.atomic
def record_offline_refund(payment, *, amount, reason, receipt, actor):
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
    _require_record_authority(actor, [locked])
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
    return refund
