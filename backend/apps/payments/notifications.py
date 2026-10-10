"""Payment edges; provider identifiers and financial amounts never enter staff chat."""

from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notifications_research import bounded, notify_family, safe_adapter


@safe_adapter
def notify_payment(payment, event, *, refund=None, requester_only=False):
    staff = bag(id=payment.pk, status=bounded(payment.status))
    own = bag(id=payment.pk, status=bounded(payment.status),
              amount=bounded(refund.amount if refund else payment.amount, 32),
              currency=bounded(payment.currency, 8), due_date=_due_date(payment))
    return notify_family(
        payment.makerspace, "payments", event, staff,
        data={"payment_id": payment.pk, "refund_id": refund.pk if refund else None},
        member_id=payment.member_id, requester_subject=own,
        requester_only=requester_only,
    )


def _due_date(payment):
    from apps.makerspaces.local_time import to_local
    return to_local(payment.makerspace, payment.due_at).date().isoformat() if payment.due_at else ""
