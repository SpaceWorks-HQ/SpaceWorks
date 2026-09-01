from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.makerspaces.models import Makerspace, MakerspaceMembership


class PresenceSession(models.Model):
    """A time-boxed declaration; expiry is derived, never rewritten by cron.

    Creation and ending belong to ``apps.presence.services``. Direct mutation is
    limited to migrations and the read-only superadmin admin surface.
    """

    class EndReason(models.TextChoices):
        SUPERSEDED = "superseded", "Superseded"
        MEMBERSHIP_REVOKED = "membership_revoked", "Membership revoked"
        CLAIM_REVOKED = "claim_revoked", "Claim revoked"
        USER_ENDED = "user_ended", "User ended"

    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    makerspace = models.ForeignKey(Makerspace, on_delete=models.CASCADE)
    membership = models.ForeignKey(MakerspaceMembership, on_delete=models.PROTECT)
    created_via_claim_session = models.ForeignKey(
        "accounts.MemberClaimCode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presence_sessions",
    )
    started_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ended_presence_sessions",
    )
    end_reason = models.CharField(max_length=24, choices=EndReason.choices, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("started_at")),
                name="presence_session_expires_after_start",
            )
        ]
        indexes = [
            models.Index(fields=["makerspace", "expires_at"]),
            models.Index(fields=["member", "makerspace", "expires_at"]),
        ]

    def clean(self):
        if self.membership_id and self.makerspace_id and (
            self.membership.makerspace_id != self.makerspace_id
            or self.membership.user_id != self.member_id
        ):
            raise ValidationError("Membership must belong to the member and makerspace.")
