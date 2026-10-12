"""Tenant or platform keyed addresses; never store plaintext email."""

from django.conf import settings
from django.db import models


class EmailSuppression(models.Model):
    class Reason(models.TextChoices):
        BOUNCE = "bounce", "Hard bounce"
        COMPLAINT = "complaint", "Spam complaint"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", null=True, blank=True, on_delete=models.CASCADE,
    )
    address_hash = models.CharField(max_length=64)
    reason = models.CharField(max_length=16, choices=Reason.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["makerspace", "address_hash"], name="uniq_space_suppressed_email",
        ), models.UniqueConstraint(
            fields=["address_hash"], condition=models.Q(makerspace__isnull=True),
            name="uniq_platform_suppressed_email",
        )]
