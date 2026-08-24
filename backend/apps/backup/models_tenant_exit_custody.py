"""Deployment-local custody state for Lane D tenant-exit envelopes."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class MakerspaceTenantExitCustodyState(models.Model):
    class State(models.TextChoices):
        HEALTHY = "healthy", "Healthy"
        DEGRADED_ONE_RECIPIENT = (
            "degraded_one_recipient",
            "Degraded: one recipient",
        )
        FLOOR_BREACHED_ZERO = "floor_breached_zero", "Floor breached: zero"

    makerspace = models.OneToOneField(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="tenant_exit_custody_state",
    )
    state = models.CharField(
        max_length=32,
        choices=State.choices,
        default=State.HEALTHY,
    )
    reason_code = models.CharField(max_length=64, blank=True)
    entered_at = models.DateTimeField(default=timezone.now)
    cleared_at = models.DateTimeField(null=True, blank=True)
    last_alarm_at = models.DateTimeField(null=True, blank=True)
    triggering_recipient = models.ForeignKey(
        "backup.MakerspaceArchiveRecipient",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="triggered_tenant_exit_custody_states",
    )
    alarm_episode = models.PositiveBigIntegerField(default=0)
    alarm_revision = models.PositiveBigIntegerField(default=0)


class TenantExitCustodyAlarmDelivery(models.Model):
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
        related_name="tenant_exit_custody_alarm_deliveries",
    )
    alarm_revision = models.PositiveBigIntegerField()
    cycle = models.PositiveIntegerField(default=0)
    channel = models.CharField(max_length=32, choices=Channel.choices)
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tenant_exit_custody_alarm_deliveries",
    )
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
        related_name="tenant_exit_custody_alarm_deliveries",
    )
    notification = models.ForeignKey(
        "notifications.Notification",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tenant_exit_custody_alarm_deliveries",
    )
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "claimed_at"),
                name="backup_texit_status_idx",
            ),
            models.Index(
                fields=("makerspace", "alarm_revision", "cycle"),
                name="backup_texit_revision_idx",
            ),
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
                name="uniq_tenant_exit_alarm_targeted",
            ),
            models.UniqueConstraint(
                fields=("makerspace", "alarm_revision", "cycle", "channel"),
                condition=models.Q(recipient_ref__isnull=True),
                name="uniq_tenant_exit_alarm_untargeted",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(channel="tenant_inapp", recipient_ref__isnull=True)
                    | models.Q(
                        channel__in=("tenant_email", "operator_email"),
                        recipient_ref__isnull=False,
                    )
                ),
                name="tenant_exit_alarm_channel_ref",
            ),
        ]
