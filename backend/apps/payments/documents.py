"""Transactional numbering and idempotent issue from settled ledger rows."""

from django.db import transaction

from apps.audit import services as audit
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import feature_enabled
from apps.payments.models import MakerspaceBillingSettings, ManualSettlement, Payment, PaymentDocument, Refund


@transaction.atomic
def issue_receipt(payment, *, actor=None, settlement=None):
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status not in (Payment.Status.PAID_ONLINE, Payment.Status.PAID_OFFLINE):
        raise ValueError("Only collected payments receive a receipt.")
    if payment.status == Payment.Status.PAID_OFFLINE:
        settlement = settlement or ManualSettlement.effective_for(payment)
        if settlement is None or settlement.payment_id != payment.pk:
            raise ValueError("Offline receipt requires a settlement on this payment.")
    if settlement and settlement.amends_id:
        previous = PaymentDocument.objects.filter(payment=payment, settlement_id=settlement.amends_id, reverses__isnull=True).first()
        if previous:
            _issue(payment, kind="credit_note",
                   actor=actor, reverses=previous, money_at=previous.money_at,
                   method=previous.settlement_method, reference=previous.settlement_reference,
                   amount=previous.amount)
    return _issue(payment, kind="receipt", actor=actor, settlement=settlement,
                  money_at=settlement.received_at if settlement else payment.updated_at,
                  method=settlement.method if settlement else payment.provider,
                  reference=settlement.reference if settlement else "", amount=payment.amount)


@transaction.atomic
def issue_credit_note(refund, *, actor=None):
    # Same lock order as refunds and settlements: Payment before the tenant counter.
    payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
    refund = Refund.objects.get(pk=refund.pk)
    if refund.status != Refund.Status.SUCCEEDED:
        raise ValueError("Only succeeded refunds receive a credit note.")
    if refund.amends_id:
        previous = PaymentDocument.objects.filter(payment=payment, refund_id=refund.amends_id, reverses__isnull=True).first()
        if previous:
            _issue(payment, kind="receipt", actor=actor,
                   reverses=previous, money_at=previous.money_at, method=previous.settlement_method,
                   reference=previous.settlement_reference, amount=previous.amount)
    return _issue(payment, kind="credit_note", actor=actor,
                  refund=refund, money_at=refund.refunded_at or refund.settled_at,
                  method=refund.method or refund.provider, reference=refund.reference, amount=refund.amount)


def _issue(payment, *, kind, actor, money_at, method, reference, amount,
           settlement=None, refund=None, reverses=None):
    query = PaymentDocument.objects.filter(payment=payment)
    if reverses:
        query = query.filter(reverses=reverses)
    elif settlement:
        query = query.filter(settlement=settlement)
    elif refund:
        query = query.filter(refund=refund)
    else:
        query = query.filter(kind="receipt", settlement__isnull=True, refund__isnull=True, reverses__isnull=True)
    existing = query.first()
    if existing:
        return existing
    space = payment.makerspace
    if not feature_enabled(space, "billing.documents") and not payment.documents.exists():
        return None
    # The parent row exists even before billing policy is configured. Locking it also
    # serializes concurrent first-use get_or_create and prefix edits through the API.
    Makerspace.objects.select_for_update().get(pk=space.pk)
    policy, _ = MakerspaceBillingSettings.objects.get_or_create(makerspace=space)
    policy = MakerspaceBillingSettings.objects.select_for_update().get(pk=policy.pk)
    number = policy.next_document_number
    document = PaymentDocument.objects.create(
        makerspace=space, payment=payment, settlement=settlement, refund=refund,
        reverses=reverses, sequence=number, number=f"{policy.number_prefix}{number:06d}",
        kind=kind, issued_by=actor,
        issuer={"name": policy.legal_name or space.name, "address": policy.address,
                "tax_id": policy.tax_id, "footer": policy.footer},
        payer_label=payment.member.username if payment.member_id else "Account-less payer",
        payer_type="member" if payment.member_id else "account_less",
        lines=[{"label": payment.subject_label or payment.get_subject_type_display(),
                "quantity": "1", "unit_amount": str(amount), "total": str(amount)}],
        amount=amount, currency=payment.currency, settlement_method=method,
        settlement_reference=reference, money_at=money_at,
    )
    policy.next_document_number = number + 1
    policy.save(update_fields=["next_document_number"])
    audit.record(actor, "payment.document_issued", makerspace=space, target=document,
                 meta={"kind": kind, "number": document.number})
    from apps.payments.document_delivery import email_document
    transaction.on_commit(lambda: email_document(document.pk))
    return document
