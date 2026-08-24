"""Project-owned JWT classes bound to one deployment generation."""

from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


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
    def for_user(cls, user):
        if getattr(user, "is_tenant_dump_stub", False):
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed("Account is not available.")
        token = super().for_user(user)
        token["auth_generation"] = current_auth_generation()
        return token
