import secrets

"""Event invitations contain digests only; clear codes are returned once."""

from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import F, Q


class EventInvite(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="invites")
    code_digest = models.CharField(max_length=64, editable=False, default=secrets.token_hex)
    email_digest = models.CharField(max_length=64, blank=True, editable=False, default="")
    max_uses = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.event_id and self.event.makerspace_id != self.makerspace_id:
            raise ValidationError({"event": "Event must belong to this makerspace."})

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "code_digest"], name="event_invite_unique_code"),
            models.CheckConstraint(condition=Q(max_uses__gte=1), name="event_invite_positive_limit"),
            models.CheckConstraint(condition=Q(uses__lte=F("max_uses")), name="event_invite_usage_limit"),
        ]
