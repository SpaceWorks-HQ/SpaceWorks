"""Refunds: a separate ledger line, because a terminal Payment row may never change.

A refund is money going back on a charge that was really collected online. The Payment
row is immutable once terminal (Postgres trigger), so refund state lives here and only
here: one row per refund attempt, PENDING until the provider confirms, then SUCCEEDED or
FAILED, never edited afterwards. Partial refunds are several rows; the invariant that
their (pending + succeeded) sum never exceeds the charge is enforced by the service
under the Payment row lock and re-checked in `clean()` as a last line of defence.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum

from apps.payments.models_payment import Payment
from apps.payments.models_settings import currency_validator


class Refund(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    #: Statuses that count against the refundable balance. A failed attempt returned
    #: nothing, so it must not block a retry.
    COUNTED_STATUSES = (Status.PENDING, Status.SUCCEEDED)

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, validators=[currency_validator])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=16, choices=Payment.Provider.choices)
    external_refund_id = models.CharField(max_length=255, null=True, blank=True)
    # Staff-authored, short, shown on the receipt. Financial metadata: never a person's
    # contact details or free-form PII -- the same rule as `Payment.subject_label`.
    reason = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="created_refunds"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="refund_amount_positive"),
            # Scoped by provider for the same reason as Payment's external ids: two
            # vendors are free to mint the same opaque id.
            models.UniqueConstraint(
                fields=["provider", "external_refund_id"],
                name="refund_external_once_per_provider",
                condition=models.Q(external_refund_id__isnull=False),
            ),
        ]

    def __str__(self):
        return f"Refund {self.pk} ({self.status}) on payment {self.payment_id}"

    @classmethod
    def counted_total(cls, payment, *, exclude_pk=None):
        """Sum of refunds that hold or have returned money on `payment`."""
        rows = cls.objects.filter(payment=payment, status__in=cls.COUNTED_STATUSES)
        if exclude_pk is not None:
            rows = rows.exclude(pk=exclude_pk)
        return rows.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    def clean(self):
        self.currency = (self.currency or "").lower()
        currency_validator(self.currency)
        if self.amount is None or self.amount <= 0:
            raise ValidationError({"amount": "Refund amount must be positive."})
        if self.status in self.COUNTED_STATUSES and self.payment_id:
            payment = Payment.objects.filter(pk=self.payment_id).only("amount").first()
            if payment is not None and (
                self.counted_total(payment, exclude_pk=self.pk) + self.amount > payment.amount
            ):
                raise ValidationError({"amount": "Refunds exceed the payment amount."})

    def save(self, *args, **kwargs):
        if self.pk:
            original = (
                type(self).objects.filter(pk=self.pk).values("status", "amount", "payment_id").first()
            )
            if original and original["status"] != self.Status.PENDING and (
                original["status"] != self.status or original["amount"] != self.amount
            ):
                raise ValidationError("Settled refunds are immutable.")
            if original and original["payment_id"] != self.payment_id:
                raise ValidationError("A refund cannot move between payments.")
        self.full_clean()
        return super().save(*args, **kwargs)
