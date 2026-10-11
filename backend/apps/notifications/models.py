from django.db import models

from .models_broadcasts import MemberBroadcast
from .models_inbox import MemberNotificationPreference, NotificationInboxRow


class Notification(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.INFO)
    event = models.CharField(max_length=64, blank=True)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url_path = models.CharField(max_length=300, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["makerspace", "read_at", "-created_at"]),
            models.Index(fields=["makerspace", "-created_at"]),
        ]

    def __str__(self):
        return self.title
