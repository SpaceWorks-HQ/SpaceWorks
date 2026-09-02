from django.conf import settings
from django.db import models


class EventOrganizer(models.Model):
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="organizers",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="organized_events",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    source_series_organizer = models.ForeignKey(
        "events.EventSeriesOrganizer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="occurrence_organizers",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "organization"),
                name="uniq_event_organizer_organization",
            ),
        ]
