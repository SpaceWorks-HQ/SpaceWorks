from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from apps.encryption.mappers import ScopedPiiModelMixin

from django.utils import timezone
from .models_spaces import BookableSpace


class Booking(ScopedPiiModelMixin, models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No-show"

    space = models.ForeignKey(
        BookableSpace,
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    public_token = models.UUIDField(
        default=uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    name = models.TextField()
    email = models.TextField()
    phone = models.TextField()
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )
    note = models.TextField(blank=True)
    custom_answers = models.JSONField(null=True, blank=True, default=None)
    calendar_sequence = models.PositiveIntegerField(default=0)
    calendar_updated_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="booking_end_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["space", "status", "starts_at"],
                name="booking_space_status_idx",
            ),
            models.Index(
                fields=["space", "ends_at"],
                name="booking_space_end_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip()
        self.email = (self.email or "").strip().lower()
        self.phone = (self.phone or "").strip()
        errors = {
            field: "This field may not be blank."
            for field in ("name", "email", "phone")
            if not getattr(self, field)
        }
        if errors:
            raise ValidationError(errors)
        if self.pk:
            original = type(self).objects.only("public_token", "space_id").get(
                pk=self.pk
            )
            self.public_token = original.public_token
            self.space_id = original.space_id
        super().save(*args, **kwargs)
