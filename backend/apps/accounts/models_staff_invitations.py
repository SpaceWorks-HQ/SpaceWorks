"""Deployment-local invitations to staff authority, stored as bearer digests."""

from django.conf import settings
from django.db import models


class StaffInvitation(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    email_ciphertext = models.TextField()
    role = models.ForeignKey("makerspaces.MakerspaceRole", on_delete=models.CASCADE)
    granted_actions = models.JSONField(default=list)
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="staff_invitations_created")
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name="staff_invitations_accepted")
    created_at = models.DateTimeField(auto_now_add=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)

    @property
    def email(self):
        from apps.makerspaces.secrets import decrypt_value
        return decrypt_value(self.email_ciphertext)
