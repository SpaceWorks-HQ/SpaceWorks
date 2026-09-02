from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.events.models_event import Event
from apps.events.models_registration import EventRegistration
from apps.makerspaces.models import Makerspace


class EventCheckInEvent(models.Model):
    """Immutable evidence that an attended transition happened."""

    class Source(models.TextChoices):
        ONLINE = "online", "Online staff confirmation"
        QR = "qr", "Online QR check-in"
        OFFLINE_SYNC = "offline_sync", "Authenticated offline synchronization"
        VENUE_STATION = "venue_station", "PIN venue station"
        LEGACY = "legacy", "Legacy attendance history"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.PROTECT,
        related_name="event_check_in_events",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        related_name="check_in_events",
    )

    registration = models.ForeignKey(
        EventRegistration,
        on_delete=models.PROTECT,
        related_name="check_in_events",
    )
    operation_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    source = models.CharField(max_length=16, choices=Source.choices)
    # The scan/confirmation time. Offline clients report it; recorded_at remains the
    # server-controlled receipt time so delayed synchronization never rewrites history.
    attended_at = models.DateTimeField(default=timezone.now)
    recorded_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    session_id = models.UUIDField(null=True, blank=True, editable=False)
    station_version = models.PositiveIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["attended_at", "id"]
        indexes = [
            models.Index(
                fields=["registration", "attended_at"],
                name="event_checkin_history_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source__in=("online", "qr", "offline_sync"),
                        actor__isnull=False,
                        station_version__isnull=True,
                    )
                    | models.Q(
                        source="venue_station",
                        actor__isnull=True,
                        station_version__isnull=False,
                    )
                    | models.Q(source="legacy", station_version__isnull=True)
                ),
                name="event_checkin_source_actor_consistent",
            ),
        ]

    def clean(self):
        super().clean()
        if self.registration_id and self.event_id:
            if self.registration.event_id != self.event_id:
                raise ValidationError("Registration must belong to the check-in event.")
        if self.event_id and self.makerspace_id:
            if self.event.makerspace_id != self.makerspace_id:
                raise ValidationError("Check-in event must belong to the host makerspace.")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("EventCheckInEvent rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("EventCheckInEvent rows are immutable.")


class EventCheckInStationCredential(models.Model):
    """Mutable, event-scoped PIN authority; attendee data never lives here."""

    event = models.OneToOneField(
        Event,
        on_delete=models.CASCADE,
        related_name="check_in_station",
    )
    public_token = models.UUIDField(default=uuid4, unique=True, editable=False)
    pin_digest = models.CharField(max_length=128, editable=False)
    pin_ciphertext = models.BinaryField(editable=False)
    version = models.PositiveIntegerField(default=1, editable=False)
    is_enabled = models.BooleanField(default=True)
    rotated_at = models.DateTimeField(default=timezone.now)
    disabled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
