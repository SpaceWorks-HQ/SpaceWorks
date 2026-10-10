"""Core billing policy; no credentials or rail prerequisite."""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models


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

    def clean(self):
        for name in ("reminder_days_before", "reminder_days_after"):
            values = getattr(self, name)
            if (not isinstance(values, list) or len(values) > 20 or
                    any(type(day) is not int or not 1 <= day <= 365 for day in values) or
                    len(set(values)) != len(values)):
                raise ValidationError({name: "Use at most 20 distinct whole days between 1 and 365."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
