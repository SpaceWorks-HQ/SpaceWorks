"""Immutable issued financial documents, permanently part of the core ledger."""

from django.core.exceptions import ValidationError
from django.db import models
from decimal import Decimal, InvalidOperation


class PaymentDocument(models.Model):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        CREDIT_NOTE = "credit_note", "Credit note"

    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    payment = models.ForeignKey("payments.Payment", on_delete=models.CASCADE, related_name="documents")
    settlement = models.ForeignKey("payments.ManualSettlement", null=True, blank=True, on_delete=models.CASCADE)
    refund = models.ForeignKey("payments.Refund", null=True, blank=True, on_delete=models.CASCADE)
    reverses = models.OneToOneField("self", null=True, blank=True, on_delete=models.CASCADE, related_name="reversed_by")
    sequence = models.PositiveBigIntegerField()
    number = models.CharField(max_length=80)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    issuer = models.JSONField(default=dict)
    # Label only, never contact details or embedded user IDs. Ownership is Payment.member.
    payer_label = models.CharField(max_length=150)
    payer_type = models.CharField(max_length=16)
    lines = models.JSONField(default=list)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    settlement_method = models.CharField(max_length=16)
    settlement_reference = models.CharField(max_length=64, blank=True)
    money_at = models.DateTimeField()
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT)
    # Reserved for an owner-approved tax design. Always NULL; no tax is computed.
    tax_breakdown = models.JSONField(null=True, blank=True, default=None)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["makerspace", "sequence"], name="document_space_sequence"),
            models.UniqueConstraint(fields=["makerspace", "number"], name="document_space_number"),
            models.UniqueConstraint(fields=["makerspace", "settlement"], condition=models.Q(settlement__isnull=False), name="document_settlement_once"),
            models.UniqueConstraint(fields=["makerspace", "refund"], condition=models.Q(refund__isnull=False), name="document_refund_once"),
            models.UniqueConstraint(fields=["makerspace", "payment"], condition=models.Q(
                settlement__isnull=True, refund__isnull=True, reverses__isnull=True, kind="receipt"), name="document_online_once"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="document_amount_positive"),
            models.CheckConstraint(condition=models.Q(sequence__gt=0), name="document_sequence_positive"),
            models.CheckConstraint(condition=models.Q(tax_breakdown__isnull=True), name="document_tax_unused"),
        ]

    def clean(self):
        if sum(bool(source) for source in (self.settlement_id, self.refund_id, self.reverses_id)) > 1:
            raise ValidationError("A document must have only one financial source.")
        if (not isinstance(self.issuer, dict) or not isinstance(self.issuer.get("name"), str)
                or not self.issuer["name"].strip() or any(
                    not isinstance(self.issuer.get(key, ""), str) for key in ("address", "tax_id", "footer"))):
            raise ValidationError("Invalid document issuer snapshot.")
        if self.payment_id and self.payment.makerspace_id != self.makerspace_id:
            raise ValidationError("Document must belong to the payment's makerspace.")
        for source in (self.settlement, self.refund, self.reverses):
            if source and source.payment_id != self.payment_id:
                raise ValidationError("Document sources must refer to the same payment.")
        if self.currency != self.payment.currency or self.payment.status not in ("paid_online", "paid_offline"):
            raise ValidationError("Document must match a collected payment's currency.")
        if self.reverses:
            if self.kind == self.reverses.kind or self.amount != self.reverses.amount:
                raise ValidationError("A reversal must offset the original document exactly.")
        elif self.refund:
            if self.kind != "credit_note" or self.refund.status != "succeeded" or self.amount != self.refund.amount:
                raise ValidationError("A credit note must match a succeeded refund.")
        elif self.kind != "receipt" or self.amount != self.payment.amount:
            raise ValidationError("A receipt must match the full collected amount.")
        if self.settlement and (self.kind != "receipt" or self.amount != self.settlement.amount):
            raise ValidationError("A settlement receipt must match its settlement.")
        try:
            if not self.lines or not isinstance(self.lines, list) or any(
                not isinstance(line, dict) or not isinstance(line.get("label"), str) or
                not line["label"].strip() or
                not all(Decimal(line[key]).is_finite() for key in ("quantity", "unit_amount", "total")) or
                Decimal(line["quantity"]) <= 0 or Decimal(line["unit_amount"]) < 0 or
                Decimal(line["quantity"]) * Decimal(line["unit_amount"]) != Decimal(line["total"])
                for line in self.lines
            ) or sum(Decimal(line["total"]) for line in self.lines) != Decimal(self.amount):
                raise ValidationError("Document lines must reconcile to the total.")
        except (InvalidOperation, TypeError, KeyError, ValueError):
            raise ValidationError("Invalid document lines.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Payment documents are append-only.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Payment documents are append-only.")
