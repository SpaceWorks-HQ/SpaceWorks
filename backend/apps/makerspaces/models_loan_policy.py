"""Tenant loan settings; a missing row preserves the legacy return policy."""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def default_reminder_offsets():
    return [0]


def validate_reminder_offsets(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValidationError("Use a list of at most 100 reminder offsets in hours.")
    if any(type(offset) is not int or not -8760 <= offset <= 8760 for offset in value):
        raise ValidationError("Offsets must be whole hours between -8760 and 8760.")
    if len(set(value)) != len(value):
        raise ValidationError("Reminder offsets must be unique.")


class MakerspaceLoanPolicy(models.Model):
    class RenewalMode(models.TextChoices):
        OFF = "off", "Off"
        AUTO = "auto", "Automatic within policy"

    makerspace = models.OneToOneField(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="loan_policy",
    )
    default_loan_days = models.PositiveIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    loan_renewal_mode = models.CharField(max_length=16, choices=RenewalMode.choices, default=RenewalMode.OFF)
    loan_max_renewals = models.PositiveIntegerField(default=1, validators=[MaxValueValidator(100)])
    loan_renewal_days = models.PositiveIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    loan_max_active = models.PositiveIntegerField(default=0)
    loan_max_items = models.PositiveIntegerField(default=0)
    loan_reminder_offsets_hours = models.JSONField(default=default_reminder_offsets, validators=[validate_reminder_offsets])
    loan_escalate_overdue_days = models.PositiveIntegerField(default=0, validators=[MaxValueValidator(365)])
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def for_makerspace(cls, makerspace):
        # Reading defaults must not turn on the ladder by creating a policy row.
        return cls.objects.filter(makerspace=makerspace).first() or cls(
            makerspace=makerspace, default_loan_days=makerspace.default_loan_days or 7,
        )
