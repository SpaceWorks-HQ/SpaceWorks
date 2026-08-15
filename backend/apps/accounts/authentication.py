from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.accounts.claim_routes import CLAIM_REACHABLE_PREFIXES
from apps.accounts.models import User
from apps.accounts.models_devices import DeviceGrant, DeviceRefreshFamily


class SpaceWorksJWTAuthentication(JWTAuthentication):
    """Adds immediate device-grant checks while preserving ordinary JWT behavior."""

    def authenticate(self, request):
        authenticated = super().authenticate(request)
        if authenticated is None:
            return None
        user, token = authenticated
        if token.get("surface") == "staff":
            _validate_staff_surface(request, token)
        if token.get("surface") == "member" and not _member_surface_path_allowed(
            request.path
        ):
            raise PermissionDenied("Member sessions cannot access staff APIs.")
        grant_id = token.get("device_grant_id")
        if grant_id is None:
            if request.headers.get("X-Makerspace-Id") is not None:
                raise PermissionDenied("Native makerspace selection requires a device grant.")
            return authenticated
        family_id = token.get("device_family_id")
        if not family_id:
            raise AuthenticationFailed("Invalid device authorization.")
        grant = DeviceGrant.objects.filter(pk=grant_id, user=user).first()
        valid = bool(
            grant and grant.status == DeviceGrant.Status.ACTIVE
            and user.is_active and user.access_status == User.AccessStatus.ACTIVE
            and DeviceRefreshFamily.objects.filter(
                pk=family_id, grant=grant, user=user, revoked_at__isnull=True
            ).exists()
        )
        if not valid:
            raise AuthenticationFailed("Device authorization is no longer active.")
        request.device_grant = grant
        from apps.makerspaces.origin_scope import validate_native_makerspace_scope

        validate_native_makerspace_scope(request, user, grant)
        DeviceGrant.objects.filter(pk=grant.pk).update(last_used_at=timezone.now())
        return user, token


# Preserve SimpleJWT's documented Bearer security scheme after replacing its
# authenticator with the device-grant-aware subclass above.
from drf_spectacular.contrib.rest_framework_simplejwt import (  # noqa: E402
    SimpleJWTScheme,
)


class SpaceWorksJWTScheme(SimpleJWTScheme):
    target_class = "apps.accounts.authentication.SpaceWorksJWTAuthentication"


def _member_surface_path_allowed(path):
    return path.startswith(CLAIM_REACHABLE_PREFIXES)


def _validate_staff_surface(request, token):
    from apps.accounts.social_nonces import request_origin
    from apps.makerspaces.cors import staff_origin_is_registered
    from apps.makerspaces.origin_scope import (
        AMBIGUOUS_STAFF_ORIGIN_SCOPE,
        NO_STAFF_ORIGIN_SCOPE,
        staff_origin_scope,
    )

    if not staff_origin_is_registered(request_origin(request)):
        raise PermissionDenied("Staff social sessions require a trusted staff origin.")
    actual = staff_origin_scope(request)
    expected = str(token.get("staff_scope") or "")
    if actual is AMBIGUOUS_STAFF_ORIGIN_SCOPE:
        raise PermissionDenied("Staff origin is ambiguous.")
    if expected == "platform":
        if actual is not NO_STAFF_ORIGIN_SCOPE:
            raise PermissionDenied("Staff session origin does not match.")
    elif str(actual) != expected:
        raise PermissionDenied("Staff session origin does not match.")
