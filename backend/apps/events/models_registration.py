from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from apps.encryption.mappers import ScopedPiiModelMixin
from apps.events.models_event import Event


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
    # MONEY, not activity: NOT cleared by the collaborator's `events` purge. A waitlisted row
    # is charged only at `_promote()`, so a purge in between would null the field above and
    # route the charge to the host, which the visitor cannot reach -- and no `Payment` exists
    # yet to carry it. Resurrects nothing: history/profile/QR read the field above, not this.
    payment_via_makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="event_registration_payment_routes",
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
