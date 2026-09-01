from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.encryption.mappers import ScopedPiiModelMixin
from apps.events.models_feedback import EventFeedbackResponse
from apps.events.models_registration import EventRegistration


class EventAttendanceCertificate(ScopedPiiModelMixin, models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RENDERING = "rendering", "Rendering"
        ACTIVE = "active", "Active"
        FAILED = "failed", "Failed"
        REVOKED = "revoked", "Revoked"

    class RevocationReason(models.TextChoices):
        ATTENDANCE_CORRECTED = "attendance_corrected", "Attendance corrected"
        EVENT_CANCELLED = "event_cancelled", "Event cancelled"
        STAFF_REVOKED = "staff_revoked", "Staff revoked"

    response = models.ForeignKey(
        EventFeedbackResponse,
        on_delete=models.PROTECT,
        related_name="certificates",
    )
    registration = models.ForeignKey(
        EventRegistration,
        on_delete=models.PROTECT,
        related_name="attendance_certificates",
    )
    serial = models.UUIDField(default=uuid4, unique=True, editable=False)
    revision = models.PositiveIntegerField()
    recipient_name = models.TextField()
    event_title = models.CharField(max_length=200)
    event_starts_at = models.DateTimeField()
    event_ends_at = models.DateTimeField()
    issuer_name = models.CharField(max_length=200)
    object_key = models.CharField(max_length=512, unique=True)
    content_type = models.CharField(max_length=64, default="application/pdf")
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    rendered_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    revocation_reason = models.CharField(
        max_length=32,
        choices=RevocationReason.choices,
        blank=True,
    )

    class Meta:
        ordering = ["registration_id", "revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["registration", "revision"],
                name="uniq_event_certificate_revision",
            ),
            models.UniqueConstraint(
                fields=["registration"],
                condition=~Q(status="revoked"),
                name="uniq_live_event_certificate",
            ),
        ]

    def clean(self):
        super().clean()
        if self.response_id and self.registration_id:
            if self.response.registration_id != self.registration_id:
                raise ValidationError(
                    {"response": "Response and certificate registration must match."}
                )
        if self.content_type != "application/pdf":
            raise ValidationError({"content_type": "Certificates must be PDF files."})

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            issuance_fields = (
                "response_id", "registration_id", "serial", "revision",
                "recipient_name", "event_title", "event_starts_at",
                "event_ends_at", "issuer_name", "object_key", "content_type",
                "issued_at",
            )
            if any(
                getattr(self, field) != getattr(original, field)
                for field in issuance_fields
            ):
                raise ValidationError("Certificate issuance snapshots are immutable.")
            allowed = {
                self.Status.PENDING: {self.Status.RENDERING},
                self.Status.FAILED: {self.Status.RENDERING},
                self.Status.RENDERING: {self.Status.ACTIVE, self.Status.FAILED},
                self.Status.ACTIVE: {self.Status.REVOKED},
                self.Status.REVOKED: set(),
            }
            if self.status != original.status and self.status not in allowed[original.status]:
                raise ValidationError({"status": "Invalid certificate transition."})
            if original.status == self.Status.ACTIVE:
                frozen = ("size_bytes", "sha256", "rendered_at")
                if any(getattr(self, field) != getattr(original, field) for field in frozen):
                    raise ValidationError("An active certificate artifact is immutable.")
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)
