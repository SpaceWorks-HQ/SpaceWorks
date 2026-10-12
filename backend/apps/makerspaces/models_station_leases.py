"""Transient kiosk Station authority: human operator leases and session revocations.

Both tables are deployment-local and omitted from every tenant archive. A lease never
stores its bearer token; the client holds a signed token naming this row, and every
call re-checks the row, the Station credential and the user's live authority.
"""

from uuid import uuid4

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


class StationOperatorLease(models.Model):
    """A short-lived binding of one signed-in staff User to one Station session."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="station_operator_leases",
    )
    station = models.ForeignKey(
        "makerspaces.Station",
        on_delete=models.CASCADE,
        related_name="operator_leases",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="station_operator_leases",
    )
    station_session_id = models.UUIDField()
    station_version = models.PositiveIntegerField()
    allowed_actions = ArrayField(models.CharField(max_length=64), default=list, size=32)
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("expires_at",), name="station_lease_expiry_idx"),
            models.Index(
                fields=("station", "station_session_id"),
                name="station_lease_session_idx",
            ),
        ]


class StationSessionRevocation(models.Model):
    """Deny-only record of a Station session ended before its signed expiry."""

    session_id = models.UUIDField(primary_key=True, editable=False)
    station = models.ForeignKey(
        "makerspaces.Station",
        on_delete=models.CASCADE,
        related_name="session_revocations",
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=("expires_at",), name="station_revocation_expiry_idx"),
        ]
