"""Personal delivery state, separate from the legacy makerspace-wide feed."""

from django.conf import settings
from django.db import models

from apps.encryption.mappers import ScopedPiiModelMixin


class NotificationInboxRow(ScopedPiiModelMixin, models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    feature = models.CharField(max_length=32)
    event = models.CharField(max_length=64)
    # One lifecycle fan-out has one identity, even when a user has several roles.
    event_key = models.UUIDField()
    title = models.TextField()
    summary = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(
            fields=["makerspace", "user", "event_key"], name="uniq_personal_inbox_event",
        )]
        indexes = [models.Index(
            fields=["makerspace", "user", "read_at", "-created_at"],
            name="personal_inbox_unread_idx",
        )]


class MemberNotificationPreference(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    feature = models.CharField(max_length=32)
    channel = models.CharField(max_length=16)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["makerspace", "user", "feature", "channel"],
            name="uniq_member_notify_pref",
        )]
