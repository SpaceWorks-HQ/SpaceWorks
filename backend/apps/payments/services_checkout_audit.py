"""Audit attribution for newly persisted hosted-payment checkout capabilities."""

from apps.audit import services as audit


def record_checkout_created(payment, *, actor=None):
    """Record checkout creation without copying its bearer URL into immutable audit."""
    audit.record(
        actor or payment.created_by,
        "payment.checkout_created",
        makerspace=payment.makerspace,
        target=payment,
        meta={
            "payment_id": payment.pk,
            "provider": payment.provider,
            "subject_type": payment.subject_type,
            "subject_id": payment.subject_id,
        },
    )
