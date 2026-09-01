from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.events.models_registration import EventRegistration


class EventCheckInEvent(models.Model):
    """Immutable evidence that an attended transition happened."""

    class Source(models.TextChoices):
        STAFF = "staff", "Staff confirmation"
        QR = "qr", "QR check-in"

    registration = models.ForeignKey(
        EventRegistration,
        on_delete=models.CASCADE,
        related_name="check_in_events",
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    attended_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["attended_at", "id"]
        indexes = [
            models.Index(
                fields=["registration", "attended_at"],
                name="event_checkin_history_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("EventCheckInEvent rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("EventCheckInEvent rows are immutable.")
