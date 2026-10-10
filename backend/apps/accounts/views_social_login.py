from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import audit_events
from apps.accounts.attestation import (
    AttestationRejected,
    AttestationUnavailable,
    verify_attestation,
)
from apps.accounts.auth_cookies import set_refresh_cookies
from apps.accounts.login_methods import self_registration_enabled, social_login_enabled
from apps.accounts.member_identity import member_login_allowed
from apps.accounts.models_oidc import provider_for_slug, provider_key
from apps.accounts.models_social import SocialProvider, SocialSurface
from apps.accounts.serializers import user_payload
from apps.accounts.serializers_device import DeviceGrantSerializer
from apps.accounts.serializers_social import (
    SocialLoginResponseSerializer,
    SocialLoginSerializer,
    SocialNonceResponseSerializer,
    SocialNonceSerializer,
)
from apps.accounts.services_social_identity import (
    SocialResolutionError,
    resolve_social_identity,
)
from apps.accounts.services_social_login import (
    SocialDeviceGrantRetryRequired,
    assert_staff_authority,
    issue_social_session,
    social_audit_meta,
)
from apps.accounts.social_jwt import SocialProviderUnavailable, SocialTokenError
from apps.accounts.social_nonces import (
    SocialAuthUnavailable,
    SocialDeviceRestartRequired,
    SocialNonceRejected,
    consume_social_nonce,
    create_social_nonce,
    provider_settings,
)
from apps.openapi_errors import errors
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.import_adoption import adopt_pending_memberships_for_user
from apps.makerspaces.origin_scope import NO_STAFF_ORIGIN_SCOPE, staff_origin_scope


from apps.accounts.views_social_helpers import _error, _audit_failure


class SocialNonceView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "social_nonce"

    @extend_schema(tags=["Social auth"], auth=[], request=SocialNonceSerializer,
        responses={200: SocialNonceResponseSerializer, **errors(400, 403, 404, 429)})
    def post(self, request):
        serializer = SocialNonceSerializer(data=request.data, context={"request": request})
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
        responses={200: SocialLoginResponseSerializer, **errors(400, 401, 403, 404, 409, 429, 503), 409: OpenApiResponse(ErrorSerializer, description="Includes `social_device_restart_required` when burned pre-grant inputs must be replaced.")})
    def post(self, request):
        serializer = SocialLoginSerializer(data=request.data, context={"request": request})
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
        nonce_row = None
        try:
            _settings, audience = provider_settings(self.provider, data["client_platform"])
            nonce_row, attestation_challenge = consume_social_nonce(
                request, raw=data["nonce"], provider=self.provider,
                surface=data["surface"], delivery=data["delivery"],
                client_platform=data["client_platform"],
                raw_challenge=data.get("challenge"), provider_audience=audience,
            )
            verified_attestation = None
            if attestation_challenge is not None:
                verified_attestation = verify_attestation(
                    attestation_challenge,
                    data["challenge"],
                    data["attestation"],
                )
            from apps.accounts.views_social import _verify
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
            if (
                data["delivery"] == "device"
                and nonce_row.device_grant_id is not None
                and nonce_row.device_grant.user_id != user.pk
            ):
                raise SocialResolutionError("access_denied", 403)
            adopt_pending_memberships_for_user(user)
            scope = staff_origin_scope(request)
            staff_scope = None if scope is NO_STAFF_ORIGIN_SCOPE else str(scope)
            tokens = issue_social_session(
                user,
                surface=data["surface"],
                delivery=data["delivery"],
                nonce_row=nonce_row,
                staff_scope=staff_scope,
                verified_attestation=verified_attestation,
            )
            if data["delivery"] == "device":
                request.device_grant = tokens["device_grant"]
        except SocialAuthUnavailable:
            return _error("social_unavailable", 404)
        except SocialDeviceRestartRequired:
            _audit_failure(self.provider, "device_restart_required")
            return _error("social_device_restart_required", 409)
        except SocialTokenError:
            _audit_failure(self.provider, "invalid")
            if nonce_row is not None and nonce_row.attestation_challenge_id:
                return _error("social_device_restart_required", 409)
            return _error("social_invalid", 401)
        except SocialNonceRejected:
            _audit_failure(self.provider, "invalid")
            return _error("social_invalid", 401)
        except (AttestationRejected, AttestationUnavailable):
            _audit_failure(self.provider, "attestation_failed")
            return _error("social_device_restart_required", 409)
        except SocialProviderUnavailable:
            if nonce_row is not None and nonce_row.attestation_challenge_id:
                _audit_failure(self.provider, "provider_unavailable")
                return _error("social_device_restart_required", 409)
            return _error("social_unavailable", 503)
        except SocialDeviceGrantRetryRequired:
            _audit_failure(self.provider, "device_grant_failed")
            return _error("social_device_restart_required", 409)
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



