from django.conf import settings
from django.db import models

from apps.integrations.email_templates_registry import validate_email_template_strings
from apps.makerspaces.secrets import decrypt_value, encrypt_value
from apps.encryption.mappers import ScopedPiiModelMixin

class EmailTemplate(models.Model):
    class Stream(models.TextChoices):
        HARDWARE = "hardware", "Hardware"
        PRINTING = "printing", "Printing"
        EVENTS = "events", "Events"
        BOOKINGS = "bookings", "Bookings"
        MAINTENANCE = "maintenance", "Maintenance"
        # `membership`, not `members`: the feature key and the stream name genuinely
        # differ here, and existing EmailLog rows already carry `membership`.
        MEMBERSHIP = "membership", "Membership"

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

