from uuid import uuid4

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from apps.forms_schema.validation import validate_form_schema


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    class LocationKind(models.TextChoices):
        INDOOR = 'indoor', 'Indoor'
        OUTDOOR = 'outdoor', 'Outdoor'
        OTHER = 'other', 'Other'

    public_token = models.UUIDField(
        default=uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="events",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=255, blank=True)
    location_kind = models.CharField(
        max_length=8,
        choices=LocationKind.choices,
        default=LocationKind.OTHER,
    )
    custom_form = models.JSONField(
        null=True,
        blank=True,
        default=None,
        validators=[validate_form_schema],
    )
    capacity = models.PositiveIntegerField(default=0)
    payment_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    is_public = models.BooleanField(default=False)
    # Public-bucket object key for the event cover image. Managed only by the
    # dedicated image endpoints (never by the generic update path), so it is
    # deliberately absent from services.EVENT_FIELDS.
    image_key = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gte=F("starts_at")),
                name="event_ends_not_before_start",
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=0),
                name="event_capacity_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(payment_amount__gte=0),
                name="event_payment_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["makerspace", "starts_at"],
                name="event_ms_starts_idx",
            ),
            models.Index(
                fields=["makerspace", "status", "starts_at"],
                name="event_ms_status_start_idx",
            ),
            models.Index(
                fields=["makerspace", "is_public", "status", "ends_at"],
                name="event_public_lookup_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        if self.pk:
            original = type(self).objects.only("public_token", "makerspace_id").get(
                pk=self.pk
            )
            self.public_token = original.public_token
            self.makerspace_id = original.makerspace_id
        super().save(*args, **kwargs)
