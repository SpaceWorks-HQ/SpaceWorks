"""Single-row queue and challenge state for account recovery."""

from django.db import models
from django.db.models.functions import Lower


class PasswordResetEnvelopeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CLAIMED = "claimed", "Claimed"
    DELIVERING = "delivering", "Delivering"
    ISSUED = "issued", "Issued"
    CONSUMED = "consumed", "Consumed"
    DISCARDED = "discarded", "Discarded"
    UNDELIVERABLE = "undeliverable", "Undeliverable"
    DELIVERY_UNKNOWN = "delivery_unknown", "Delivery unknown"


class PasswordResetEnvelope(models.Model):
    """One reusable recovery envelope for each normalized global email address.

    The stable row is both the request queue item and the confirmation lock target.
    Unknown addresses deliberately get the same row shape as known addresses so the
    anonymous request path never needs to look up an account.
    """

    email_normalized = models.CharField(max_length=254)
    email_fingerprint = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    digest_is_live = models.BooleanField(default=False)
    credential_fingerprint = models.CharField(max_length=64, blank=True)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="password_reset_envelopes",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=PasswordResetEnvelopeStatus.choices,
        default=PasswordResetEnvelopeStatus.PENDING,
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_owner = models.CharField(max_length=128, blank=True)
    claim_expires_at = models.DateTimeField(null=True, blank=True)
    generation = models.PositiveBigIntegerField(default=0)
    requested_at = models.DateTimeField()
    superseded_at = models.DateTimeField(null=True, blank=True)
    terminal_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email_normalized"),
                name="uniq_password_reset_email_ci",
            )
        ]
        indexes = [
            models.Index(fields=["status", "requested_at"]),
            models.Index(fields=["status", "claim_expires_at"]),
            models.Index(fields=["terminal_at"]),
        ]

    def __str__(self):
        return f"Password reset envelope #{self.pk} [{self.status}]"
