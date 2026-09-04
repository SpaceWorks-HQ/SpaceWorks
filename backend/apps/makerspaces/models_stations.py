from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone


class Station(models.Model):
    """Tenant-owned metadata for a physical or browser Station channel."""

    class Kind(models.TextChoices):
        EVENT_CHECKIN = "event_checkin", "Event check-in"
        SCANNER = "scanner", "Scanner"
        HANDOVER = "handover", "Handover"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="stations",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    name = models.CharField(max_length=160)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_stations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("makerspace", "kind", "name"),
                name="uniq_station_name_per_space_kind",
            ),
        ]


class StationCredential(models.Model):
    """Live bearer and PIN authority for exactly one Station."""

    station = models.OneToOneField(
        Station,
        on_delete=models.CASCADE,
        related_name="credential",
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
