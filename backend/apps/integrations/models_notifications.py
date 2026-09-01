from django.conf import settings
from django.db import models

from apps.integrations.notification_enums import (
    NonEmailNotificationChannel,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationFeature,
)


class NotificationPreference(models.Model):
    """Per-makerspace (feature, channel) on/off cell. Additive — absence means the
    catalog default; it never alters EmailNotificationMute's exact-row semantics."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    feature = models.CharField(max_length=32, choices=NotificationFeature.choices)
    channel = models.CharField(max_length=16, choices=NotificationChannel.choices)
    enabled = models.BooleanField()
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "feature", "channel"],
                name="uniq_notify_pref_cell",
            )
        ]
        ordering = ["makerspace_id", "feature", "channel"]

    def __str__(self):
        return f"{self.makerspace_id}:{self.feature}/{self.channel}={self.enabled}"


class NotificationDeliveryLog(models.Model):
    """Durable status/retry record for the non-email channels. NEVER stores a webhook URL,
    Telegram token/chat id, auth header, or provider response body — the destination is
    resolved from the makerspace at attempt time (like email's live SMTP)."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="notification_delivery_logs",
    )
    channel = models.CharField(
        max_length=16, choices=NonEmailNotificationChannel.choices
    )
    # Nullable twice over, for two different reasons. Rows written before destinations
    # existed have none, and native push addresses a user rather than a room. SET_NULL so
    # deleting a room does not erase its delivery history.
    destination = models.ForeignKey(
        "integrations.NotificationDestination",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="delivery_logs",
    )
    # Snapshot of the room's name, and the only way to tell "never had a destination" from
    # "the destination was deleted" once the FK is nulled. Delivery refuses the second
    # case rather than falling back to the makerspace-wide webhook, which would post a
    # machine-scoped alert into the general channel.
    destination_label = models.CharField(max_length=80, blank=True, default="")
    feature = models.CharField(max_length=32, choices=NotificationFeature.choices)
    event = models.CharField(max_length=64)
    text_body = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=8,
        choices=NotificationDeliveryStatus.choices,
        default=NotificationDeliveryStatus.PENDING,
    )
    error = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["makerspace", "channel", "-created_at"],
                name="notifylog_space_chan_idx",
            ),
            models.Index(fields=["status"], name="notifylog_status_idx"),
            models.Index(
                fields=["makerspace", "status", "-created_at"],
                name="notifylog_space_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.makerspace_id}:{self.channel}/{self.event}={self.status}"


class DailyNotificationCounter(models.Model):
    """Managed per-day send counter for a non-email channel (fair-use cap). Distinct from
    DailyEmailCounter; dormant on self-host."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="daily_notification_counters",
    )
    channel = models.CharField(
        max_length=16, choices=NonEmailNotificationChannel.choices
    )
    day = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "channel", "day"],
                name="uniq_daily_notify_counter",
            )
        ]

    def __str__(self):
        return f"{self.makerspace_id}:{self.channel}:{self.day}={self.count}"
