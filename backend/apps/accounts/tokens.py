"""Project-owned JWT classes bound to one deployment generation."""

from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from django.db import transaction


def current_auth_generation():
    from apps.backup.models import DeploymentRecoveryState

    return str(DeploymentRecoveryState.load().auth_generation)


def validate_auth_generation(token):
    from rest_framework_simplejwt.exceptions import AuthenticationFailed

    if str(token.get("auth_generation") or "") != current_auth_generation():
        raise AuthenticationFailed(
            "This session belongs to a different authentication generation.",
            code="auth_generation_mismatch",
        )


class _GenerationBoundToken:
    def verify(self, *args, **kwargs):
        super().verify(*args, **kwargs)
        validate_auth_generation(self)


class SpaceWorksAccessToken(_GenerationBoundToken, AccessToken):
    """Bearer token accepted only by the deployment generation that minted it."""


class SpaceWorksRefreshToken(_GenerationBoundToken, RefreshToken):
    access_token_class = SpaceWorksAccessToken

    @classmethod
    @transaction.atomic
    def for_user(cls, user):
        # A credential change also locks User. Hold that same lock through both
        # verification and minting so an unenrolled login cannot pick up the new
        # credential's version between these reads without proving its factor.
        from apps.accounts.models import User
        # NO KEY UPDATE remains compatible with FK inserts by concurrent native
        # logins; FOR UPDATE here could deadlock their shared FK-lock upgrades.
        locked = User.objects.select_for_update(no_key=True).get(pk=user.pk)
        if hasattr(user, "_mfa_verified_version"):
            locked._mfa_verified_version = user._mfa_verified_version
        user = locked
        if getattr(user, "is_tenant_dump_stub", False):
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed("Account is not available.")
        from apps.accounts.mfa_policy import assert_verified, credential
        assert_verified(user)
        token = super().for_user(user)
        row = credential(user)
        if row:
            token["mfa_version"] = str(row.version)
        token["auth_generation"] = current_auth_generation()
        return token
