from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.events.models_event import Event


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
    source_series_collaboration = models.ForeignKey(
        "events.EventSeriesCollaborator",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="occurrence_collaborators",
    )

    class Meta:
        unique_together = (("event", "makerspace"),)

    def clean(self):
        super().clean()
        if self.event_id and self.makerspace_id == self.event.makerspace_id:
            raise ValidationError(
                {"makerspace": "An event's host makerspace cannot be a collaborator."}
            )
