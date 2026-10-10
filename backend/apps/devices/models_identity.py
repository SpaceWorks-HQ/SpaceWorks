"""Device identity: the principal, its one-time enrollments and its replay nonces.

A Device is NOT an ``accounts.User``. It never appears as an audit actor, an evidence
uploader or a scan actor; its identity travels as typed audit metadata plus an
append-only ``DeviceEvent``. Every status/key change goes through the named services in
``services_enrollment`` / ``services_identity`` -- there is no serializer or admin write.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.makerspaces.models import Makerspace


class Device(models.Model):
    class Kind(models.TextChoices):
        PRINTER = "printer", "Printer"
        LABEL_PRINTER = "label_printer", "Label printer"
        GENERIC = "generic", "Generic"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending enrollment"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey(
        Makerspace, on_delete=models.CASCADE, related_name="devices"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # Canonical base64 of the raw 32-byte Ed25519 public key. Public material, but it is
    # only meaningful on the deployment where proof of possession happened.
    public_key = models.CharField(max_length=64, null=True, blank=True)
    # SHA-256 hex of the raw key; deployment-unique so one key is one device.
    key_fingerprint = models.CharField(max_length=64, null=True, blank=True, unique=True)
    # Monotonic: every completed enrollment/rotation increments it, and a signed request
    # must name the current value, so an old key's signatures die with the swap.
    key_version = models.PositiveIntegerField(default=0)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    offline_threshold_seconds = models.PositiveIntegerField(default=300)
    # Reserved for phase 7d (scheduled offline detection); 7a never writes them.
    offline_since = models.DateTimeField(null=True, blank=True)
    offline_notified_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("name", "id")
        indexes = [models.Index(fields=["makerspace", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(offline_threshold_seconds__gte=1),
                name="devices_device_offline_threshold_positive",
            ),
            models.CheckConstraint(
                condition=~Q(status="active")
                | (Q(public_key__isnull=False) & Q(key_fingerprint__isnull=False)),
                name="devices_device_active_has_key",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.kind})"


class DeviceEnrollment(models.Model):
    """A one-time, staff-issued bearer that lets a device prove possession of a key.

    The raw token and server challenge are returned once and never stored: only their
    SHA-256 digests live here. Consumed, revoked and expired rows never revive.
    """

    class Purpose(models.TextChoices):
        ENROLL = "enroll", "Enroll"
        ROTATE = "rotate", "Rotate"
        REACTIVATE = "reactivate", "Reactivate"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey(
        Makerspace, on_delete=models.CASCADE, related_name="device_enrollments"
    )
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="enrollments")
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    token_digest = models.CharField(max_length=64, unique=True)
    candidate_key_fingerprint = models.CharField(max_length=64, blank=True, default="")
    challenge_digest = models.CharField(max_length=64, blank=True, default="")
    challenge_issued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        indexes = [models.Index(fields=["device", "used_at", "revoked_at"])]

    def is_open(self, now):
        return self.used_at is None and self.revoked_at is None and self.expires_at > now


class DeviceRequestNonce(models.Model):
    """The authoritative replay record: one INSERT per accepted signed request."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="+")
    key_version = models.PositiveIntegerField()
    nonce_digest = models.CharField(max_length=64)
    claimed_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["device", "expires_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=("device", "key_version", "nonce_digest"),
                name="devices_nonce_unique_per_device_key",
            )
        ]
