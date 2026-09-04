"""Invitation requests: "I would like to join" from someone who is not yet a member.

Forward plan phase 6 ("Invitation requests"). The public makerspace site accepts a
name, contact and message from an anonymous visitor; staff see the queue beside join
requests and either **Invite** (which issues the ordinary membership invitation through
`membership_services.invite_membership`) or decline. Nothing here grants anything: the
row is a lead, and the invitation it turns into is the existing, audited path.

Privacy shape: `name`, `email` and `phone` are scoped source PII registered in
`apps/encryption/registry.py` and encrypted at rest when encryption is enabled, like the
requester fields on `HardwareRequest`. They are TextFields for that reason -- an envelope
is longer than the plaintext limit the registry enforces.
"""
from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models

from apps.encryption.mappers import ScopedPiiModelMixin


class InvitationRequest(ScopedPiiModelMixin, models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        INVITED = "invited", "Invited"
        DECLINED = "declined", "Declined"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="invitation_requests"
    )
    name = models.TextField(blank=True, default="")
    email = models.TextField(blank=True, default="")
    phone = models.TextField(blank=True, default="")
    message = models.TextField(blank=True, default="", validators=[MaxLengthValidator(1000)])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="handled_invitation_requests",
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["makerspace", "status", "created_at"],
                name="invitationreq_ms_status_idx",
            ),
        ]
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"invitation request {self.pk} ({self.makerspace_id})"
