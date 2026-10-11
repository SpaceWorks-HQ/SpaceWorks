"""Core billing policy; no credentials or rail prerequisite."""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models


def default_account_codes():
    return {"income": "4000", "cash": "1000", "online": "1010", "deposit": "2100"}


def validate_account_codes(value):
    from apps.payments.models_payment import Payment
    allowed = {"income", "cash", "online", "deposit", *Payment.SubjectType.values}
    if (not isinstance(value, dict) or set(value) - allowed or
            any(not isinstance(code, str) or not code.strip() or len(code) > 32 or
                any(ord(char) < 32 for char in code) for code in value.values())):
        raise ValidationError("Use recognized account keys and nonempty codes of at most 32 characters.")


def reminder_before_default():
    return [3]


def reminder_after_default():
    return [7]


class MakerspaceBillingSettings(models.Model):
    makerspace = models.OneToOneField(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="billing_settings",
    )
    # Zero means due on raise. The date is snapshotted on each new charge.
    payment_terms_days = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(365)])
    reminder_days_before = models.JSONField(default=reminder_before_default, blank=True)
    reminder_days_after = models.JSONField(default=reminder_after_default, blank=True)
    max_reminders = models.PositiveSmallIntegerField(default=2, validators=[MaxValueValidator(20)])
    number_prefix = models.CharField(max_length=32, blank=True, default="")
    legal_name = models.CharField(max_length=150, blank=True, default="")
    address = models.TextField(max_length=1000, blank=True, default="")
    tax_id = models.CharField(max_length=64, blank=True, default="")
    footer = models.TextField(max_length=1000, blank=True, default="")
    account_codes = models.JSONField(default=default_account_codes, validators=[validate_account_codes], blank=True)
    # Internal sequence, never exposed as an editable API field. Rolled back with issue.
    next_document_number = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(next_document_number__gt=0), name="billing_document_counter_positive")]

    def clean(self):
        validate_account_codes(self.account_codes)
        if any(ord(char) < 32 or char in "/\\" for char in self.number_prefix):
            raise ValidationError({"number_prefix": "Use a prefix without control characters or slashes."})
        for name in ("reminder_days_before", "reminder_days_after"):
            values = getattr(self, name)
            if (not isinstance(values, list) or len(values) > 20 or
                    any(type(day) is not int or not 1 <= day <= 365 for day in values) or
                    len(set(values)) != len(values)):
                raise ValidationError({name: "Use at most 20 distinct whole days between 1 and 365."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
