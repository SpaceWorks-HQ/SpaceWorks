from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import audit_events
from apps.accounts.auth_cookies import set_refresh_cookies
from apps.accounts.login_methods import self_registration_enabled, social_login_enabled
from apps.accounts.member_identity import member_login_allowed
from apps.accounts.models_oidc import provider_for_slug, provider_key, slug_from_provider_key
from apps.accounts.models_social import SocialIdentity, SocialProvider, SocialSurface
from apps.accounts.serializers import user_payload
from apps.accounts.serializers_device import DeviceGrantSerializer
from apps.accounts.serializers_social import (
    SocialIdentitySerializer,
    SocialLinkSerializer,
    SocialLoginResponseSerializer,
    SocialLoginSerializer,
    SocialNonceResponseSerializer,
    SocialNonceSerializer,
)
from apps.accounts.services_social_identity import (
    SocialResolutionError,
    resolve_social_identity,
    unlink_social_identity,
)
from apps.accounts.services_social_login import (
    assert_staff_authority,
    issue_social_session,
    social_audit_meta,
)
from apps.accounts.social_jwt import SocialProviderUnavailable, SocialTokenError
from apps.accounts.social_nonces import (
    SocialAuthUnavailable,
    SocialNonceRejected,
    consume_social_nonce,
    create_social_nonce,
    provider_settings,
)
from apps.audit import services as audit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.origin_scope import NO_STAFF_ORIGIN_SCOPE, staff_origin_scope


def _error(code, status_code):
    messages = {
        "social_unavailable": "Social sign-in is unavailable.",
        "social_invalid": "Social sign-in could not be verified.",
        "account_link_required": "Sign in with an existing credential to link this account.",
        "staff_access_required": "An existing staff account is required.",
        "identity_conflict": "That provider identity is linked to another account.",
        "provider_already_linked": "A different identity from that provider is already linked.",
        "last_credential": "Add another sign-in method before removing this one.",
        "identity_not_found": "That provider is not linked.",
        "access_denied": "Account access is restricted.",
        "registration_disabled": "Account registration is not available.",
    }
    return Response({"detail": messages.get(code, messages["social_invalid"]), "code": code}, status=status_code)


class SocialNonceView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "social_nonce"

    @extend_schema(tags=["Social auth"], auth=[], request=SocialNonceSerializer,
        responses={200: SocialNonceResponseSerializer, 400: OpenApiResponse(ErrorSerializer), 404: OpenApiResponse(ErrorSerializer), 429: OpenApiResponse(ErrorSerializer)})
    def post(self, request):
        serializer = SocialNonceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            raw = create_social_nonce(request, **serializer.validated_data)
        except SocialAuthUnavailable:
            return _error("social_unavailable", 404)
        except SocialNonceRejected:
            return _error("social_invalid", 403)
        return Response({"nonce": raw, "expires_in": settings.SOCIAL_AUTH_NONCE_TTL_SECONDS})


class SocialLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "social_login"
    provider = None

    @extend_schema(tags=["Social auth"], auth=[], request=SocialLoginSerializer,
        responses={200: SocialLoginResponseSerializer, 401: OpenApiResponse(ErrorSerializer), 403: OpenApiResponse(ErrorSerializer), 404: OpenApiResponse(ErrorSerializer), 409: OpenApiResponse(ErrorSerializer), 429: OpenApiResponse(ErrorSerializer)})
    def post(self, request):
        serializer = SocialLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # A member-surface login through a built-in consumer provider is part of the
        # member-account ecosystem, so it goes when `accounts` does. The STAFF surface
        # and any configured OIDC provider are exempt -- see `member_identity` for why
        # both exemptions are load-bearing. Answered before the nonce is consumed, so a
        # gated attempt cannot burn a one-time nonce.
        if not member_login_allowed(self.provider, surface=data["surface"]):
            return _error("social_unavailable", 404)
        # The platform switch covers the built-ins and every configured OIDC provider
        # alike -- they share this endpoint. Same 404 an unconfigured provider gets:
        # both mean "this deployment does not offer that", and the caller has no use for
        # the distinction.
        if not social_login_enabled():
            return _error("social_unavailable", 404)
        try:
            _settings, audience = provider_settings(self.provider, data["client_platform"])
            nonce_row = consume_social_nonce(request, raw=data["nonce"], provider=self.provider,
                surface=data["surface"], delivery=data["delivery"], client_platform=data["client_platform"])
            claims = _verify(self.provider, data["id_token"], data["nonce"], audience)
            validator = (
                lambda user: assert_staff_authority(user, request)
                if data["surface"] == SocialSurface.STAFF else None
            )
            user, outcome = resolve_social_identity(provider=self.provider, claims=claims,
                surface=data["surface"], apple_name=data.get("apple_name", ""),
                staff_validator=validator if data["surface"] == SocialSurface.STAFF else None,
                allow_user_creation=self_registration_enabled(),
                # Only an OIDC provider can forbid auto-linking; the built-ins always
                # verify email ownership, so `claims` carries no such key for them.
                allow_auto_link=claims.get("allow_auto_link", True))
            if data["delivery"] == "device" and nonce_row.device_grant.user_id != user.pk:
                raise SocialResolutionError("access_denied", 403)
            scope = staff_origin_scope(request)
            staff_scope = (
                None if scope is NO_STAFF_ORIGIN_SCOPE else str(scope)
            )
            tokens = issue_social_session(
                user,
                surface=data["surface"],
                delivery=data["delivery"],
                nonce_row=nonce_row,
                staff_scope=staff_scope,
            )
        except SocialAuthUnavailable:
            return _error("social_unavailable", 404)
        except (SocialNonceRejected, SocialTokenError):
            _audit_failure(self.provider, "invalid")
            return _error("social_invalid", 401)
        except SocialProviderUnavailable:
            return _error("social_unavailable", 503)
        except SocialResolutionError as exc:
            # The nonce is already consumed by the time resolution can refuse, so this is
            # a state-changing path and has to leave a trace -- the same rule the phone
            # `_confirm` guard follows. Returning an error does not make an already
            # committed `consumed_at` read-only.
            _audit_failure(self.provider, exc.code)
            return _error(exc.code, exc.status_code)
        audit_events.record_auth_event(user, "auth.social_login_succeeded", target=user,
            meta=social_audit_meta(self.provider, outcome, claims["sub"]))
        payload = {"access": tokens["access"], "user": user_payload(user, request=request), "outcome": outcome}
        if data["delivery"] == "device":
            payload.update({"refresh": tokens["refresh"], "device_grant": DeviceGrantSerializer(tokens["device_grant"]).data})
            return Response(payload)
        response = Response(payload)
        set_refresh_cookies(response, tokens["refresh"], request)
        return response


class GoogleSocialLoginView(SocialLoginView):
    provider = SocialProvider.GOOGLE


class AppleSocialLoginView(SocialLoginView):
    provider = SocialProvider.APPLE


class OidcSocialLoginView(SocialLoginView):
    """Login through a deployment-configured OIDC provider named in the URL.

    The slug is resolved to a configured row on every request rather than captured at
    import time, so disabling a provider takes effect immediately instead of at the next
    restart -- the same reason `provider_for_slug` refuses disabled and half-filled rows.
    """

    @property
    def provider(self):
        return provider_key(self.kwargs["slug"])


class SocialProviderListLinkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Social auth"], responses={200: SocialIdentitySerializer(many=True)})
    def get(self, request):
        rows = SocialIdentity.objects.filter(user=request.user).order_by("provider")
        return Response(SocialIdentitySerializer(rows, many=True).data)

    @extend_schema(tags=["Social auth"], request=SocialLinkSerializer,
        responses={200: SocialIdentitySerializer, 401: OpenApiResponse(ErrorSerializer), 409: OpenApiResponse(ErrorSerializer)})
    def post(self, request):
        serializer = SocialLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            _settings, audience = provider_settings(data["provider"], data["client_platform"])
            consume_social_nonce(request, raw=data["nonce"], provider=data["provider"],
                surface="member", delivery="web", client_platform=data["client_platform"])
            claims = _verify(data["provider"], data["id_token"], data["nonce"], audience)
            resolve_social_identity(provider=data["provider"], claims=claims, surface="member",
                apple_name=data.get("apple_name", ""), explicit_user=request.user)
        except SocialAuthUnavailable:
            return _error("social_unavailable", 404)
        except (SocialNonceRejected, SocialTokenError):
            return _error("social_invalid", 401)
        except SocialProviderUnavailable:
            return _error("social_unavailable", 503)
        except SocialResolutionError as exc:
            # Same reasoning as the login view: the nonce was consumed before
            # `_explicit_link` could refuse a walk-in record, so the refusal is recorded
            # against a real actor rather than left as a silent 403.
            audit_events.record_auth_event(
                request.user, "auth.social_identity_link_failed", target=request.user,
                meta={"provider": data["provider"], "reason": exc.code},
            )
            return _error(exc.code, exc.status_code)
        identity = SocialIdentity.objects.get(user=request.user, provider=data["provider"])
        audit.record(request.user, "auth.social_identity_linked", target=request.user,
            meta={"provider": data["provider"], "subject_hash": audit_events.fingerprint(claims["sub"])})
        return Response(SocialIdentitySerializer(identity).data)


class SocialProviderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Social auth"], request=None, responses={204: None, 404: OpenApiResponse(ErrorSerializer), 409: OpenApiResponse(ErrorSerializer)})
    def delete(self, request, provider):
        if provider not in SocialProvider.values:
            return _error("identity_not_found", 404)
        try:
            unlink_social_identity(request.user, provider)
        except SocialResolutionError as exc:
            return _error(exc.code, exc.status_code)
        audit.record(request.user, "auth.social_identity_unlinked", target=request.user, meta={"provider": provider})
        return Response(status=status.HTTP_204_NO_CONTENT)


def _verify(provider, raw_token, nonce, audience):
    slug = slug_from_provider_key(provider)
    if slug is not None:
        from apps.accounts.social_oidc import verify_oidc_token

        row = provider_for_slug(slug)
        if row is None:
            raise SocialAuthUnavailable
        return verify_oidc_token(raw_token, nonce=nonce, provider_row=row)
    if provider == SocialProvider.GOOGLE:
        from apps.accounts.social_google import verify_google_token
        return verify_google_token(raw_token, nonce=nonce, audience=audience)
    from apps.accounts.social_apple import verify_apple_token
    return verify_apple_token(raw_token, nonce=nonce, audience=audience)


def _audit_failure(provider, reason):
    audit_events.record_auth_event(None, "auth.social_login_failed", meta={"provider": provider, "reason": reason})
