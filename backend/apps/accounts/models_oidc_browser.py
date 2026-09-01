from django.conf import settings
from django.db import models


class OidcBrowserAttempt(models.Model):
    """Single-use authorization-code attempt with three protocol secrets."""

    provider = models.CharField(max_length=64)
    state_digest = models.CharField(max_length=64, unique=True)
    nonce_digest = models.CharField(max_length=64, unique=True)
    code_verifier = models.CharField(max_length=128)
    redirect_uri = models.CharField(max_length=2048)
    origin = models.CharField(max_length=512)
    intended_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="oidc_browser_attempts",
    )
    intended_membership = models.ForeignKey(
        "makerspaces.MakerspaceMembership",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="oidc_browser_attempts",
    )
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(intended_user__isnull=True, intended_membership__isnull=True)
                    | models.Q(intended_user__isnull=False, intended_membership__isnull=False)
                ),
                name="oidc_attempt_binding_pair",
            )
        ]
        indexes = [
            models.Index(
                fields=["expires_at", "consumed_at"],
                name="oidc_attempt_use_idx",
            )
        ]
