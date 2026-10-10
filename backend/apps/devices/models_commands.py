"""Durable delivery ownership; credentials are digest-only and never exported."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class DeviceCommand(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        LEASED = "leased", "Leased"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        DELIVERY_FAILED = "delivery_failed", "Delivery failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    device = models.ForeignKey("devices.Device", on_delete=models.CASCADE, related_name="commands")
    device_key_version = models.PositiveIntegerField()
    kind = models.CharField(max_length=32, default="printer_job")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_token_digest = models.CharField(max_length=64, null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=48, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["device", "status", "next_attempt_at"], name="device_command_delivery_idx")]
        constraints = [models.CheckConstraint(
            condition=~Q(status="leased") | (Q(lease_token_digest__isnull=False) & Q(lease_expires_at__isnull=False)),
            name="device_command_lease_complete",
        )]
