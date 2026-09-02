from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
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
    calendar_uid = models.UUIDField(default=uuid4, editable=False, unique=True)
    calendar_sequence = models.PositiveIntegerField(default=0)
    calendar_updated_at = models.DateTimeField(default=timezone.now)
    timezone_name = models.CharField(max_length=64, default=settings.TIME_ZONE)
    badge_template = models.JSONField(default=dict, blank=True)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="events",
    )
    series = models.ForeignKey(
        "events.EventSeries",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="occurrences",
    )
    series_occurrence_key = models.CharField(max_length=48, null=True, blank=True)
    series_revision = models.PositiveIntegerField(null=True, blank=True)
    series_override_fields = models.JSONField(default=list, blank=True)
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
    registration_requires_approval = models.BooleanField(default=False)
    registration_cutoff_at = models.DateTimeField(null=True, blank=True)
    registration_cutoff_lead_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
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
            models.CheckConstraint(
                condition=(
                    Q(registration_cutoff_at__isnull=True)
                    | Q(registration_cutoff_lead_minutes__isnull=True)
                ),
                name="event_registration_cutoff_mode_exclusive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(registration_cutoff_at__isnull=True)
                    | Q(registration_cutoff_at__lte=F("starts_at"))
                ),
                name="event_registration_cutoff_not_after_start",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        series__isnull=True,
                        series_occurrence_key__isnull=True,
                        series_revision__isnull=True,
                    )
                    | Q(
                        series__isnull=False,
                        series_occurrence_key__isnull=False,
                        series_revision__isnull=False,
                    )
                ),
                name="event_series_identity_all_or_none",
            ),
            models.UniqueConstraint(
                fields=("series", "series_occurrence_key"),
                name="uniq_event_series_occurrence_key",
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
            models.Index(
                fields=["series", "starts_at"], name="event_series_start_idx"
            ),
        ]

    def clean(self):
        super().clean()
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValidationError({"timezone_name": "Use a valid IANA timezone name."}) from exc
        if (
            self.registration_cutoff_at is not None
            and self.registration_cutoff_lead_minutes is not None
        ):
            raise ValidationError(
                "Choose either an absolute registration cutoff or lead minutes, not both."
            )
        if (
            self.registration_cutoff_at is not None
            and self.starts_at is not None
            and self.registration_cutoff_at > self.starts_at
        ):
            raise ValidationError({
                "registration_cutoff_at": "Registration cutoff cannot be after the event starts."
            })
        identity = (
            self.series_id,
            self.series_occurrence_key,
            self.series_revision,
        )
        if any(value is None for value in identity) and any(value is not None for value in identity):
            raise ValidationError("Series occurrence identity must be entirely set or entirely empty.")
        if self.series_id and self.makerspace_id != self.series.makerspace_id:
            raise ValidationError({"series": "Series and occurrence must share a makerspace."})
        if not isinstance(self.series_override_fields, list) or any(
            not isinstance(value, str) for value in self.series_override_fields
        ):
            raise ValidationError({"series_override_fields": "Expected a list of field names."})
    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        if self.pk:
            original = type(self).objects.only(
                "public_token", "calendar_uid", "makerspace_id"
            ).get(
                pk=self.pk
            )
            self.public_token = original.public_token
            self.calendar_uid = original.calendar_uid
            self.makerspace_id = original.makerspace_id
        super().save(*args, **kwargs)
