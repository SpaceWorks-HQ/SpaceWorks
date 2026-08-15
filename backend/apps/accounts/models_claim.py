import uuid

from django.conf import settings
from django.db import models


class MemberClaimCode(models.Model):
    """A short-lived physical-handover credential, stored only as a digest."""

    membership = models.ForeignKey(
        "makerspaces.MakerspaceMembership",
        on_delete=models.CASCADE,
        related_name="claim_codes",
    )
    code_digest = models.CharField(max_length=64, unique=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="issued_member_claim_codes",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_ip = models.GenericIPAddressField(null=True, blank=True)
    absolute_expires_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revoked_member_claim_codes",
    )
    # D5 binds its bounded claim session to this identifier. It is an identifier, not
    # the bearer secret, and can therefore remain stable while the raw code is discarded.
    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        indexes = [
            models.Index(
                fields=["membership", "expires_at"],
                name="claim_membership_exp_idx",
            ),
            models.Index(
                fields=["session_id", "revoked_at"],
                name="claim_session_revoke_idx",
            ),
        ]
