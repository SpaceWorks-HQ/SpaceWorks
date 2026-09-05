"""The manual-settlement ledger: how a charge was paid when there was no online rail.

A `Payment` row records that money is OWED. When staff take that money in person --
cash, UPI, a bank transfer, a card machine, a cheque -- the row's status flips to
`paid_offline`, and this ledger records *how*, *when* and *by whom*, so the space has a
real cash book rather than a bare boolean.

Append-only by design. Putting these columns on `Payment` was rejected because the
terminal-guard trigger only protects `status` and `amount`: a receipt reference sitting
on the payment row could be quietly rewritten afterwards with nothing to show for it.
Corrections are therefore an appended `amends` row -- the same shape `Refund` and
`AuditLog` already use -- so a mistyped reference leaves both the error and the fix
visible.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.payments.models_payment import Payment
from apps.payments.models_settings import currency_validator


class ManualSettlement(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        UPI = "upi", "UPI"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        CARD_MACHINE = "card_machine", "Card machine"
        CHEQUE = "cheque", "Cheque"
        OTHER = "other", "Other"

    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="manual_settlements"
    )
    method = models.CharField(max_length=16, choices=Method.choices)
    # A short operator-entered handle: a UPI reference, a cheque number, a terminal slip
    # id. Financial metadata, never a person's contact details -- the same rule written
    # on `Payment.subject_label` and `Refund.reason`. Bounded so it cannot become a
    # free-text notes field by habit.
    reference = models.CharField(max_length=64, blank=True, default="")
    #: When the money actually changed hands, which is not always when staff recorded it.
    received_at = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, validators=[currency_validator])
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="recorded_settlements"
    )
    #: Set when this row REPLACES an earlier receipt on the same payment. The chain head
    #: -- the row nothing amends -- is the effective receipt.
    amends = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="amended_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="manual_settlement_amount_positive"
            ),
        ]

    def __str__(self):
        return f"{self.get_method_display()} settlement on payment {self.payment_id}"

    @classmethod
    def effective_for(cls, payment):
        """The receipt that currently stands: the newest row nothing has amended."""
        return (
            cls.objects.filter(payment=payment, amended_by__isnull=True)
            .order_by("-created_at", "-pk")
            .first()
        )

    def clean(self):
        self.currency = (self.currency or "").lower()
        currency_validator(self.currency)
        if self.amount is None or self.amount <= 0:
            raise ValidationError({"amount": "Settlement amount must be positive."})
        if self.received_at is None:
            raise ValidationError({"received_at": "A settlement needs a received date."})
        if self.amends_id:
            # A correction replaces a receipt on the SAME debt. Allowing it to cross
            # payments would let one space's cash book absorb another's.
            amended = type(self).objects.filter(pk=self.amends_id).values(
                "payment_id"
            ).first()
            if amended and amended["payment_id"] != self.payment_id:
                raise ValidationError(
                    {"amends": "An amendment must stay on the same payment."}
                )
            if self.amends_id == self.pk:
                raise ValidationError({"amends": "A settlement cannot amend itself."})
        if self.payment_id:
            payment = (
                Payment.objects.filter(pk=self.payment_id)
                .only("amount", "currency")
                .first()
            )
            if payment is not None:
                # Partial manual settlement is deliberately NOT introduced here: one
                # receipt settles one debt in full, so a mismatch is an operator error
                # rather than a part payment nobody can reconcile later.
                if Decimal(self.amount) != payment.amount:
                    raise ValidationError(
                        {"amount": "A settlement must match the payment amount."}
                    )
                if self.currency != payment.currency:
                    raise ValidationError(
                        {"currency": "A settlement must match the payment currency."}
                    )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "Manual settlements are append-only; record an amendment instead."
            )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Manual settlements are append-only and cannot be deleted.")
