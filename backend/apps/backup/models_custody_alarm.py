from django.conf import settings
from django.db import models


class ArchiveCustodyAlarmDelivery(models.Model):
    class Channel(models.TextChoices):
        TENANT_INAPP = "tenant_inapp", "Tenant in-app"
        TENANT_EMAIL = "tenant_email", "Tenant email"
        OPERATOR_EMAIL = "operator_email", "Operator email"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        EXHAUSTED = "exhausted", "Exhausted"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="archive_custody_alarm_deliveries",
    )
    alarm_revision = models.PositiveBigIntegerField()
    cycle = models.PositiveIntegerField(default=0)
    channel = models.CharField(max_length=32, choices=Channel.choices)
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archive_custody_alarm_deliveries",
    )
    # The FK is useful for joins but may be nulled on user deletion. This immutable
    # numeric identity keeps delivery idempotency stable after that deletion.
    recipient_ref = models.BigIntegerField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempts = models.PositiveIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    email_log = models.ForeignKey(
        "integrations.EmailLog",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archive_custody_alarm_deliveries",
    )
    notification = models.ForeignKey(
        "notifications.Notification",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archive_custody_alarm_deliveries",
    )
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(fields=("status", "next_attempt_at", "claimed_at")),
            models.Index(fields=("makerspace", "alarm_revision", "cycle")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "makerspace",
                    "alarm_revision",
                    "cycle",
                    "channel",
                    "recipient_ref",
                ),
                condition=models.Q(recipient_ref__isnull=False),
                name="uniq_custody_alarm_targeted",
            ),
            models.UniqueConstraint(
                fields=("makerspace", "alarm_revision", "cycle", "channel"),
                condition=models.Q(recipient_ref__isnull=True),
                name="uniq_custody_alarm_untargeted",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        channel="tenant_inapp",
                        recipient_ref__isnull=True,
                    )
                    | models.Q(
                        channel__in=("tenant_email", "operator_email"),
                        recipient_ref__isnull=False,
                    )
                ),
                name="custody_alarm_channel_requires_ref",
            ),
        ]
