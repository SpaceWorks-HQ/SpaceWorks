from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import audit_events
from apps.accounts.auth_cookies import set_refresh_cookies
from apps.accounts.login_methods import self_registration_enabled, social_login_enabled
from apps.accounts.models_oidc import provider_for_slug, slug_from_provider_key
from apps.accounts.oidc_browser_attempts import (
    OidcAttemptRejected,
    consume_attempt,
    start_attempt,
)
from apps.accounts.oidc_browser_http import (
    OidcProviderUnavailable,
    OidcTokenRejected,
    discover,
    exchange_code,
)
from apps.accounts.oidc_browser_resolution import resolve_browser_identity
from apps.accounts.serializers import user_payload
from apps.accounts.serializers_oidc_browser import (
    OidcBrowserCallbackSerializer,
    OidcBrowserLoginResponseSerializer,
    OidcBrowserStartResponseSerializer,
    OidcBrowserStartSerializer,
)
from apps.accounts.services_social_identity import SocialResolutionError
from apps.accounts.services_social_login import issue_social_session, social_audit_meta
from apps.accounts.social_jwt import SocialProviderUnavailable, SocialTokenError
from apps.accounts.social_oidc import verify_oidc_token
from apps.hardware_requests.exceptions import ErrorSerializer


def _error(code, status_code):
    messages = {
        "social_unavailable": "Social sign-in is unavailable.",
        "social_invalid": "Social sign-in could not be verified.",
        "identity_conflict": "That identity belongs to another account.",
        "provider_already_linked": "A different identity from that provider is already linked.",
        "account_link_required": "This provider does not allow automatic account linking.",
        "registration_disabled": "Account registration is not available.",
    }
    return Response(
        {"detail": messages.get(code, messages["social_invalid"]), "code": code},
        status=status_code,
    )


class OidcBrowserStartView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "social_nonce"

    @extend_schema(
        tags=["Social auth"],
        auth=[],
        request=OidcBrowserStartSerializer,
        responses={
            200: OidcBrowserStartResponseSerializer,
            400: OpenApiResponse(ErrorSerializer),
            403: OpenApiResponse(ErrorSerializer),
            404: OpenApiResponse(ErrorSerializer),
            503: OpenApiResponse(ErrorSerializer),
        },
    )
    def post(self, request, slug):
        serializer = OidcBrowserStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = provider_for_slug(slug)
        if provider is None or not social_login_enabled():
            return _error("social_unavailable", 404)
        try:
            document = discover(provider)
            started = start_attempt(request, provider, document, **serializer.validated_data)
        except OidcAttemptRejected:
            return _error("social_invalid", 403)
        except OidcProviderUnavailable:
            return _error("social_unavailable", 503)
        return Response(
            {
                "authorization_url": started.authorization_url,
                "state": started.state,
                "nonce": started.nonce,
                "expires_in": settings.OIDC_ATTEMPT_TTL_SECONDS,
            }
        )


class OidcBrowserCallbackView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "social_login"

    @extend_schema(
        tags=["Social auth"],
        auth=[],
        request=OidcBrowserCallbackSerializer,
        responses={
            200: OidcBrowserLoginResponseSerializer,
            400: OpenApiResponse(ErrorSerializer),
            401: OpenApiResponse(ErrorSerializer),
            403: OpenApiResponse(ErrorSerializer),
            409: OpenApiResponse(ErrorSerializer),
            503: OpenApiResponse(ErrorSerializer),
        },
    )
    def post(self, request):
        serializer = OidcBrowserCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        attempt = None
        try:
            attempt = consume_attempt(request, state=data["state"], nonce=data["nonce"])
            slug = slug_from_provider_key(attempt.provider)
            provider = provider_for_slug(slug) if slug is not None else None
            if provider is None or not social_login_enabled():
                raise OidcProviderUnavailable()
            document = discover(provider)
            raw_token = exchange_code(
                provider,
                document,
                code=data["code"],
                redirect_uri=attempt.redirect_uri,
                code_verifier=attempt.code_verifier,
            )
            claims = verify_oidc_token(raw_token, nonce=data["nonce"], provider_row=provider)
            user, outcome = resolve_browser_identity(
                attempt,
                claims,
                allow_user_creation=self_registration_enabled(),
            )
            tokens = issue_social_session(
                user,
                surface="member",
                delivery="web",
                nonce_row=attempt,
            )
        except OidcAttemptRejected:
            return _error("social_invalid", 401)
        except OidcTokenRejected:
            _audit_failure(attempt, "token_rejected")
            return _error("social_invalid", 401)
        except (OidcProviderUnavailable, SocialProviderUnavailable):
            _audit_failure(attempt, "provider_unavailable")
            return _error("social_unavailable", 503)
        except SocialTokenError:
            _audit_failure(attempt, "invalid_token")
            return _error("social_invalid", 401)
        except SocialResolutionError as exc:
            _audit_failure(attempt, exc.code)
            return _error(exc.code, exc.status_code)
        audit_events.record_auth_event(
            user,
            "auth.social_login_succeeded",
            target=user,
            meta=social_audit_meta(attempt.provider, outcome, claims["sub"]),
        )
        response = Response(
            {
                "access": tokens["access"],
                "user": user_payload(user, request=request),
                "outcome": outcome,
            }
        )
        set_refresh_cookies(response, tokens["refresh"], request)
        return response


def _audit_failure(attempt, reason):
    audit_events.record_auth_event(
        None,
        "auth.social_login_failed",
        meta={
            "provider": getattr(attempt, "provider", ""),
            "reason": reason,
        },
    )
