from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from apps.encryption.mappers import ScopedPiiModelMixin
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


# Collaboration is an invite-and-accept relationship rather than a bare M2M so a
# space cannot unilaterally attach itself to another space's event. Hosts invite by
# slug, which also avoids enumerating makerspaces they do not administer.
class EventCollaborator(models.Model):
    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="collaborators",
    )
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="event_collaborations",
    )
    status = models.CharField(
        max_length=8,
        choices=Status.choices,
        default=Status.INVITED,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("event", "makerspace"),)

    def clean(self):
        super().clean()
        if self.event_id and self.makerspace_id == self.event.makerspace_id:
            raise ValidationError(
                {"makerspace": "An event's host makerspace cannot be a collaborator."}
            )


class EventRegistration(ScopedPiiModelMixin, models.Model):
    class Status(models.TextChoices):
        REGISTERED = "registered", "Registered"
        WAITLISTED = "waitlisted", "Waitlisted"
        CANCELLED = "cancelled", "Cancelled"
        ATTENDED = "attended", "Attended"

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="registrations",
    )
    # editable=False keeps this out of ModelForms and admin. Do not re-read it in
    # save(): register() uses save(update_fields=...) on a hot path, and no application
    # code assigns the token after creation.
    checkin_token = models.UUIDField(default=uuid4, unique=True, editable=False)
    name = models.TextField()
    email = models.TextField()
    phone = models.TextField()
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_registrations",
    )
    # Accepted collaboration authorizes discovery and creation, while this durable
    # provenance records where participation happened so member history and QR access
    # survive removal of that collaboration. SET_NULL is intentional: this is routing
    # convenience, not accountability evidence, and a purge should hide the activity
    # from that space rather than be blocked.
    registered_via_makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="event_registrations_via",
    )
    # The version and timestamp are accountability evidence about a real person's
    # agreement. SET_NULL would either violate all-or-none or silently erase that
    # evidence, so the waiver itself is PROTECTed.
    host_waiver = models.ForeignKey(
        "makerspaces.MakerspaceWaiver",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accepted_by_event_registrations",
    )
    host_waiver_accepted_at = models.DateTimeField(null=True, blank=True)
    host_waiver_version_accepted = models.CharField(
        max_length=64, null=True, blank=True,
    )
    email_exact_hash = models.BinaryField(max_length=32, null=True, editable=False)
    email_hash_generation = models.ForeignKey(
        "encryption.SearchKeyGeneration", on_delete=models.PROTECT,
        null=True, editable=False,
    )
    custom_answers = models.JSONField(null=True, blank=True, default=None)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.REGISTERED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "email"],
                name="uniq_event_registration_email",
            ),
            models.UniqueConstraint(
                fields=["event", "email_hash_generation", "email_exact_hash"],
                condition=Q(email_hash_generation__isnull=False, email_exact_hash__isnull=False),
                name="uniq_event_registration_email_hash",
            ),
            models.UniqueConstraint(
                fields=["event", "member"],
                condition=Q(
                    member__isnull=False,
                    status__in=("registered", "waitlisted"),
                ),
                name="uniq_active_event_registration_member",
            ),
            models.CheckConstraint(
                condition=(
                    Q(host_waiver__isnull=True, host_waiver_accepted_at__isnull=True,
                      host_waiver_version_accepted__isnull=True)
                    | Q(host_waiver__isnull=False, host_waiver_accepted_at__isnull=False,
                        host_waiver_version_accepted__isnull=False)
                ),
                name="event_registration_host_waiver_all_or_none",
            ),
        ]
        indexes = [
            models.Index(
                fields=["event", "status", "created_at"],
                name="eventreg_status_fifo_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.host_waiver_id and self.event_id
            and self.host_waiver.makerspace_id != self.event.makerspace_id
        ):
            raise ValidationError(
                {"host_waiver": "Waiver must belong to the event's host makerspace."}
            )

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip()
        self.email = (self.email or "").strip().lower()
        self.phone = (self.phone or "").strip()
        super().save(*args, **kwargs)
