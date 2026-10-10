"""Resume paid admissions after releasing the ledger's payment lock.

Admission services lock the makerspace, request, then payment. A settlement already
owns the payment lock, so calling admission inline could invert that lock order.
Post-commit failure never rolls back money received; the admission sweep retries it.
"""

import logging

from django.db import transaction

from apps.payments.models import Payment

logger = logging.getLogger(__name__)


def resume_admission_after_settlement(payment):
    if payment.subject_type != Payment.SubjectType.MEMBERSHIP_REQUEST or payment.status not in {
        Payment.Status.PAID_ONLINE, Payment.Status.PAID_OFFLINE, Payment.Status.WAIVED,
    }:
        return
    payment_id = payment.pk

    def resume():
        try:
            from apps.makerspaces.membership_admission_payments import resume_after_payment

            resume_after_payment(payment_id)
        except Exception as exc:
            logger.warning("membership_admission_resume_failed", extra={
                "payment_id": payment_id, "failure_type": type(exc).__name__,
            })

    transaction.on_commit(resume)
