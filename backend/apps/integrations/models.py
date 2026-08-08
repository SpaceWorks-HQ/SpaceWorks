from django.conf import settings
from django.db import models

from apps.integrations.email_templates_registry import validate_email_template_strings
from apps.makerspaces.secrets import decrypt_value, encrypt_value
from apps.encryption.mappers import ScopedPiiModelMixin

class EmailTemplate(models.Model):
    class Stream(models.TextChoices):
        HARDWARE = "hardware", "Hardware"
        PRINTING = "printing", "Printing"

    class Audience(models.TextChoices):
        REQUESTER = "requester", "Requester"
        STAFF = "staff", "Staff"

    stream = models.CharField(max_length=16, choices=Stream.choices)
    audience = models.CharField(max_length=16, choices=Audience.choices)
    key = models.CharField(max_length=32)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="email_templates",
    )
    subject = models.CharField(max_length=200)
    text_body = models.TextField()
    html_body = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "stream", "audience", "key"],
                name="uniq_email_template_per_space",
            )
        ]
        ordering = ["makerspace__name", "stream", "audience", "key"]

    def clean(self):
        validate_email_template_strings(
            self.stream,
            self.audience,
            self.key,
            self.subject,
            self.text_body,
            self.html_body,
        )

    def __str__(self):
        return f"{self.makerspace}:{self.stream}/{self.audience}/{self.key}"

class PlatformEmailSettings(models.Model):
    smtp_host = models.CharField(max_length=200, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=200, blank=True)
    smtp_password = models.CharField(max_length=255, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    smtp_use_ssl = models.BooleanField(default=False)
    from_email = models.EmailField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_smtp_password(self, raw):
        self.smtp_password = encrypt_value(raw) if raw else ""

    def get_smtp_password(self):
        return decrypt_value(self.smtp_password) if self.smtp_password else ""

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Platform email settings"

class EmailLog(ScopedPiiModelMixin, models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        # Terminal and deliberate: the `email` module is off for this makerspace, so the
        # message was never attempted. Distinct from FAILED because nothing went wrong
        # and there is nothing to retry -- `retry_email_log` refuses it, and callers
        # reading `.status` must not report it as a delivery.
        SKIPPED = "skipped", "Skipped"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="email_logs",
    )
    to_email = models.TextField()
    subject = models.TextField()
    text_body = models.TextField(blank=True)
    html_body = models.TextField(blank=True)
    stream = models.CharField(max_length=32, blank=True)
    event = models.CharField(max_length=64, blank=True)
    audience = models.CharField(max_length=16, blank=True)
    connection_kind = models.CharField(max_length=16, default="makerspace")
    status = models.CharField(
        max_length=8,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["makerspace", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["makerspace", "status", "-created_at"]),
        ]

    def __str__(self):
        return f"EmailLog#{self.pk} [{self.status}]"

class DailyEmailCounter(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="daily_email_counters",
    )
    day = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "day"],
                name="uniq_daily_email_counter",
            )
        ]


class EmailNotificationMute(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="email_mutes",
    )
    target = models.CharField(max_length=32)
    stream = models.CharField(max_length=16)
    event = models.CharField(max_length=64)
    audience = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "target", "stream", "event"],
                name="uniq_email_mute_row",
            )
        ]
        ordering = ["makerspace__name", "stream", "event"]
        indexes = [
            models.Index(fields=["makerspace", "stream", "audience"]),
        ]

    def __str__(self):
        return f"{self.makerspace}:{self.target}:{self.stream}/{self.event} muted"


class NotificationFeature(models.TextChoices):
    HARDWARE_REQUESTS = "hardware_requests", "Hardware requests"
    PRINTING = "printing", "Printing"
    EVENTS = "events", "Events"
    BOOKINGS = "bookings", "Bookings"
    MAINTENANCE = "maintenance", "Maintenance"
    MEMBERS = "members", "Members"


class NotificationChannel(models.TextChoices):
    EMAIL = "email", "Email"
    TELEGRAM = "telegram", "Telegram"
    SLACK = "slack", "Slack"
    MATTERMOST = "mattermost", "Mattermost"
    DISCORD = "discord", "Discord"
    NATIVE_PUSH = "native_push", "Native push"


class NonEmailNotificationChannel(models.TextChoices):
    TELEGRAM = "telegram", "Telegram"
    SLACK = "slack", "Slack"
    MATTERMOST = "mattermost", "Mattermost"
    DISCORD = "discord", "Discord"
    NATIVE_PUSH = "native_push", "Native push"


# Chat channels gated by a same-named module key.
#
# Two absences are deliberate. `native_push` is governed by the standalone `mobile.push`
# feature switch, not a module. And `email` is NOT here even though an `email` module key
# exists: some messages send regardless of it (`dispatch.EMAIL_MODULE_EXEMPT` covers
# password reset, email verification and the return reminder), so treating email as
# "gone when the module is off" would hide the matrix column while mail was still going
# out — overstating what the toggle does. Tenant email is gated by
# `dispatch.email_module_blocks`, which knows about the exemptions; this table does not.
CHANNEL_MODULE_KEYS = {
    "telegram": "telegram",
    "slack": "slack",
    "mattermost": "mattermost",
    "discord": "discord",
}


class NotificationDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    # Terminal, and neither a delivery nor a failure: the makerspace has this channel's
    # module uninstalled. Recorded rather than dropped so an operator can see what the
    # toggle suppressed -- the same contract as EmailLog.Status.SKIPPED.
    SKIPPED = "skipped", "Skipped"


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


from apps.integrations.models_push import PlatformPushSettings, PushDevice  # noqa: E402
from apps.integrations.models_sms import (  # noqa: E402
    DailyOtpSmsCounter,
    PlatformSmsSettings,
    SmsProviderChoice,
)

__all__ = [
    'DailyEmailCounter',
    'DailyNotificationCounter',
    'DailyOtpSmsCounter',
    'EmailLog',
    'EmailNotificationMute',
    'EmailTemplate',
    'NonEmailNotificationChannel',
    'NotificationChannel',
    'NotificationDeliveryLog',
    'NotificationDeliveryStatus',
    'NotificationFeature',
    'NotificationPreference',
    'PlatformEmailSettings',
    'PlatformPushSettings',
    'PlatformSmsSettings',
    'PushDevice',
    'SmsProviderChoice',
]
