from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError

from apps.accounts.claim_route_types import AnonymousRead, ControlRoute, Refused
from apps.accounts.claim_routes import policy_for
from apps.accounts.claim_sessions import (
    ClaimSessionInvalid,
    attach_claim_context,
    validated_claim_session,
)
from apps.accounts.claim_tenants import claim_tenant_matches
from apps.accounts.claim_tokens import ClaimAccessToken
from apps.accounts.claim_routes import CLAIM_REACHABLE_PREFIXES
from apps.accounts.models import User
from apps.accounts.models_devices import (
    DeviceGrant,
    DeviceRefreshFamily,
    NativeAppRegistration,
)
from apps.accounts.tokens import validate_auth_generation


VERIFICATION_ONLY_SURFACE = "verification_only"
# One-release compatibility shim: the next release rejects tokens whose surface claim
# is absent outright. During this release they receive member authority, never the old
# unrestricted behavior; staff with an old token must sign in again.
TREAT_MISSING_SURFACE_AS_MEMBER_FOR_ONE_RELEASE = True
# A staff PASSWORD session. `staff` carries a mandatory trusted-origin binding, because
# it was defined for browser social sessions -- so reusing it for password login would
# break every origin-less staff caller (management commands, server-to-server, tests).
# This surface is behaviourally what a staff password session already was, only now
# stated explicitly, so the shim above can start rejecting an absent claim next release.
# It is NOT weaker than `member` for these users: it is only ever minted for an actor who
# already passed assert_staff_authority, and RBAC still authorises every request.
STAFF_API_SURFACE = "staff_api"
_KNOWN_SESSION_SURFACES = {"member", "staff", STAFF_API_SURFACE, VERIFICATION_ONLY_SURFACE}


class SpaceWorksJWTAuthentication(JWTAuthentication):
    """Adds immediate device-grant checks while preserving ordinary JWT behavior."""

    def authenticate(self, request):
        claim_authenticated = self._authenticate_claim(request)
        if claim_authenticated is not False:
            return claim_authenticated
        authenticated = super().authenticate(request)
        if authenticated is None:
            return None
        user, token = authenticated
        validate_auth_generation(token)
        from apps.backup.recovery import assert_principal_allowed

        assert_principal_allowed(user)
        surface = _effective_session_surface(token)
        if surface == "staff":
            _validate_staff_surface(request, token)
        if user.self_registered_at is not None and user.email_verified_at is None:
            # Enforce provenance at authentication too: an older device/phone issuer
            # cannot bypass verification merely because its token says member (or, for
            # the one-release legacy case, has no surface claim).
            surface = VERIFICATION_ONLY_SURFACE
        elif surface == VERIFICATION_ONLY_SURFACE:
            # Confirmation updates the user row, so the same already-issued session
            # becomes an ordinary member session immediately after ownership is proven.
            surface = "member"
        if surface == VERIFICATION_ONLY_SURFACE and not _verification_path_allowed(
            request.path
        ):
            raise PermissionDenied(
                "Verify the account email before accessing member APIs."
            )
        if surface == "member" and not _member_surface_path_allowed(
            request.path
        ):
            raise PermissionDenied("Member sessions cannot access staff APIs.")
        grant_id = token.get("device_grant_id")
        if grant_id is None:
            if request.headers.get("X-Makerspace-Id") is not None:
                raise PermissionDenied("Native makerspace selection requires a device grant.")
            _assert_source_gate(request)
            return authenticated
        family_id = token.get("device_family_id")
        if not family_id:
            raise AuthenticationFailed("Invalid device authorization.")
        grant = (
            DeviceGrant.objects.select_related("registration")
            .filter(pk=grant_id, user=user)
            .first()
        )
        valid = bool(
            grant and grant.status == DeviceGrant.Status.ACTIVE
            and grant.registration.status == NativeAppRegistration.Status.APPROVED
            and user.is_active and user.access_status == User.AccessStatus.ACTIVE
            and DeviceRefreshFamily.objects.filter(
                pk=family_id, grant=grant, user=user, revoked_at__isnull=True
            ).exists()
        )
        if not valid:
            raise AuthenticationFailed("Device authorization is no longer active.")
        request.device_grant = grant
        request.native_app_registration = grant.registration
        from apps.makerspaces.origin_scope import validate_native_makerspace_scope

        validate_native_makerspace_scope(request, user, grant)
        _assert_source_gate(request)
        DeviceGrant.objects.filter(pk=grant.pk).update(last_used_at=timezone.now())
        return user, token

    def _authenticate_claim(self, request):
        header = self.get_header(request)
        if header is None:
            return False
        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return False
        try:
            token = ClaimAccessToken(raw_token)
        except TokenError:
            return False
        validate_auth_generation(token)

        view_name = getattr(request.resolver_match, "view_name", "") or ""
        policy = policy_for(view_name, request.method)
        if isinstance(policy, AnonymousRead):
            return None
        try:
            claim = validated_claim_session(token)
        except ClaimSessionInvalid as exc:
            from apps.presence.services import expire_claim_presence

            expire_claim_presence(token.get("claim_session_id"))
            raise AuthenticationFailed("Claim session is no longer active.") from exc
        if isinstance(policy, Refused):
            raise PermissionDenied(policy.reason)
        if not isinstance(policy, ControlRoute) and not claim_tenant_matches(
            policy.tenant,
            claim_makerspace_id=claim.membership.makerspace_id,
            view_name=view_name,
            url_kwargs=getattr(request.resolver_match, "kwargs", {}) or {},
            body=request.data,
        ):
            raise PermissionDenied("Claim session is not valid for this makerspace.")
        user = attach_claim_context(claim.membership.user, claim)
        from apps.backup.recovery import assert_principal_allowed

        assert_principal_allowed(user)
        request.claim_session = claim
        request.selected_makerspace_id = claim.membership.makerspace_id
        _assert_source_gate(request)
        return user, token


# Preserve SimpleJWT's documented Bearer security scheme after replacing its
# authenticator with the device-grant-aware subclass above.
from drf_spectacular.contrib.rest_framework_simplejwt import (  # noqa: E402
    SimpleJWTScheme,
)


class SpaceWorksJWTScheme(SimpleJWTScheme):
    target_class = "apps.accounts.authentication.SpaceWorksJWTAuthentication"


# An ordinary member session is BROADER than a bounded claim session, so it needs its own
# allowlist rather than borrowing the claim prefixes. Reusing CLAIM_REACHABLE_PREFIXES was
# invisible while only social member logins carried this surface; once every member
# password login carries it, a legitimate member-owned action outside those prefixes --
# registering a phone for push -- starts 403ing. Anything added here must be an action the
# member performs on their OWN records; staff APIs never belong.
MEMBER_SURFACE_PREFIXES = CLAIM_REACHABLE_PREFIXES + ("/api/v1/integrations/push/",)


def _member_surface_path_allowed(path):
    return path.startswith(MEMBER_SURFACE_PREFIXES)


def _verification_path_allowed(path):
    return path.rstrip("/") in {
        "/api/v1/auth/me",
        "/api/v1/auth/email-verification/resend",
        "/api/v1/auth/email-verification/confirm",
    }


def _effective_session_surface(token):
    surface = token.get("surface")
    if surface is None and TREAT_MISSING_SURFACE_AS_MEMBER_FOR_ONE_RELEASE:
        return "member"
    if surface not in _KNOWN_SESSION_SURFACES:
        raise AuthenticationFailed("Invalid session surface.")
    return surface


def _assert_source_gate(request):
    from apps.tenant_migration.gate_runtime import assert_request_write_allowed

    assert_request_write_allowed(request)


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
