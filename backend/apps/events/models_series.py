from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.forms_schema.validation import validate_form_schema


class EventSeries(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    public_token = models.UUIDField(default=uuid4, editable=False, unique=True, db_index=True)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="event_series"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True)
    location_kind = models.CharField(
        max_length=8, choices=(('indoor', 'Indoor'), ('outdoor', 'Outdoor'), ('other', 'Other')),
        default="other",
    )
    custom_form = models.JSONField(
        null=True, blank=True, default=None, validators=[validate_form_schema]
    )
    capacity = models.PositiveIntegerField(default=0)
    payment_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    registration_requires_approval = models.BooleanField(default=False)
    registration_cutoff_lead_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_public = models.BooleanField(default=False)
    image_key = models.CharField(max_length=300, blank=True, default="")

    recurrence_timezone = models.CharField(max_length=64)
    dtstart_local_date = models.DateField()
    dtstart_local_time = models.TimeField()
    recurrence_rule = models.CharField(max_length=500)
    duration_minutes = models.PositiveIntegerField()
    revision = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    last_materialized_at = models.DateTimeField(null=True, blank=True)
    last_generation_error_code = models.CharField(max_length=64, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("dtstart_local_date", "dtstart_local_time", "id")
        constraints = [
            models.CheckConstraint(condition=Q(capacity__gte=0), name="series_capacity_nonnegative"),
            models.CheckConstraint(
                condition=Q(payment_amount__gte=0), name="series_payment_nonnegative"
            ),
            models.CheckConstraint(
                condition=Q(duration_minutes__gt=0), name="series_duration_positive"
            ),
            models.CheckConstraint(condition=Q(revision__gt=0), name="series_revision_positive"),
        ]
        indexes = [
            models.Index(
                fields=("makerspace", "status", "dtstart_local_date"),
                name="series_ms_status_date_idx",
            )
        ]

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        if self.pk:
            original = type(self).objects.only("public_token", "makerspace_id").get(pk=self.pk)
            self.public_token = original.public_token
            self.makerspace_id = original.makerspace_id
        super().save(*args, **kwargs)


class EventSeriesCollaborator(models.Model):
    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    series = models.ForeignKey(EventSeries, on_delete=models.CASCADE, related_name="collaborators")
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE,
        related_name="event_series_collaborations",
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.INVITED)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("series", "makerspace"), name="uniq_series_collaborator_space"
            )
        ]

    def clean(self):
        super().clean()
        if self.series_id and self.makerspace_id == self.series.makerspace_id:
            raise ValidationError(
                {"makerspace": "A series host cannot also be its collaborator."}
            )


class EventSeriesOrganizer(models.Model):
    series = models.ForeignKey(EventSeries, on_delete=models.CASCADE, related_name="organizers")
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE,
        related_name="organized_event_series",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("series", "organization"), name="uniq_series_organizer_organization"
            )
        ]
