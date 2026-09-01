from django.core.exceptions import ValidationError
from django.db import models

from apps.integrations.email_streams import MACHINE_BEARING_STREAMS
from apps.integrations.email_templates_registry import validate_email_template_strings


class MachineTypeEmailTemplate(models.Model):
    class Stream(models.TextChoices):
        HARDWARE = "hardware", "Hardware"
        PRINTING = "printing", "Printing"
        EVENTS = "events", "Events"
        BOOKINGS = "bookings", "Bookings"
        MAINTENANCE = "maintenance", "Maintenance"
        MEMBERSHIP = "membership", "Membership"

    class Audience(models.TextChoices):
        REQUESTER = "requester", "Requester"
        STAFF = "staff", "Staff"

    stream = models.CharField(max_length=16, choices=Stream.choices)
    audience = models.CharField(max_length=16, choices=Audience.choices)
    key = models.CharField(max_length=32)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="machine_type_email_templates",
    )
    machine_type = models.ForeignKey(
        "machines.MachineType",
        on_delete=models.CASCADE,
        related_name="email_templates",
    )
    subject = models.CharField(max_length=200)
    text_body = models.TextField()
    html_body = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "machine_type", "stream", "audience", "key"],
                name="uniq_type_email_template_per_space",
            )
        ]
        ordering = [
            "makerspace__name",
            "machine_type__name",
            "stream",
            "audience",
            "key",
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.stream not in MACHINE_BEARING_STREAMS:
            errors["stream"] = "Only machine-bearing streams support type overrides."
        if self.machine_type_id and self.makerspace_id:
            if self.machine_type.makerspace_id not in (None, self.makerspace_id):
                errors["machine_type"] = (
                    "Machine type must be global or belong to this makerspace."
                )
        if errors:
            raise ValidationError(errors)
        validate_email_template_strings(
            self.stream,
            self.audience,
            self.key,
            self.subject,
            self.text_body,
            self.html_body,
        )

    def __str__(self):
        return (
            f"{self.makerspace}:{self.machine_type}:"
            f"{self.stream}/{self.audience}/{self.key}"
        )
