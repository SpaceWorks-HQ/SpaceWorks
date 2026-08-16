"""Browser login, refresh, logout, and current-user endpoints."""

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts import audit_events
from apps.accounts.auth_cookies import (
    assert_csrf,
    clear_refresh_cookies,
    set_refresh_cookies,
)
from apps.accounts.login_methods import password_login_enabled
from apps.accounts.models import User
from apps.accounts.schemas_auth import (
    LoginRequestSerializer,
    LoginResponseSerializer,
    LogoutResponseSerializer,
    RefreshResponseSerializer,
    UserPayloadSerializer,
)
from apps.accounts.serializers import LoginSerializer, user_payload
from apps.openapi import LOGIN_EXAMPLE


class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    serializer_class = LoginSerializer

    @extend_schema(
        tags=["Auth"],
        summary="Log in staff user",
        auth=[],
        request=LoginRequestSerializer,
        responses={
            200: LoginResponseSerializer,
            400: OpenApiResponse(description="Invalid request."),
            401: OpenApiResponse(description="Invalid credentials or inactive account."),
            403: OpenApiResponse(description="Account access is restricted."),
            429: OpenApiResponse(description="Request throttled."),
        },
        examples=[LOGIN_EXAMPLE],
    )
    def post(self, request, *args, **kwargs):
        if not password_login_enabled():
            return Response(
                {"detail": "Password sign-in is not available on this deployment."},
                status=403,
            )
        username = request.data.get("username", "")
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except APIException:
            audit_events.record_auth_event(
                None,
                "auth.login_failed",
                meta={"username_hash": audit_events.fingerprint(username)},
            )
            raise
        data = serializer.validated_data
        refresh = data.pop("refresh")
        audit_events.record_auth_event(
            serializer.user,
            "auth.login_succeeded",
            target=serializer.user,
            meta={"username_hash": audit_events.fingerprint(username)},
        )
        response = Response({"access": data["access"], "user": data["user"]})
        set_refresh_cookies(response, refresh, request)
        return response


def _refresh_user_is_active(token_str):
    """Return False if the refresh token's user is suspended/restricted/inactive."""
    try:
        token = RefreshToken(token_str)
    except TokenError:
        return True
    user = User.objects.filter(pk=token.get("user_id")).first()
    return bool(
        user and user.is_active and user.access_status == User.AccessStatus.ACTIVE
    )


def _refresh_surface(token_str):
    try:
        return RefreshToken(token_str).get("surface")
    except TokenError:
        return None


def _assert_staff_refresh_scope(request, token_str):
    try:
        token = RefreshToken(token_str)
    except TokenError:
        return
    if token.get("surface") != "staff":
        return
    from rest_framework.exceptions import PermissionDenied

    from apps.makerspaces.origin_scope import (
        AMBIGUOUS_STAFF_ORIGIN_SCOPE,
        NO_STAFF_ORIGIN_SCOPE,
        staff_origin_scope,
    )

    actual = staff_origin_scope(request)
    expected = str(token.get("staff_scope") or "")
    if actual is AMBIGUOUS_STAFF_ORIGIN_SCOPE:
        raise PermissionDenied("Staff origin is ambiguous.")
    if expected == "platform" and actual is NO_STAFF_ORIGIN_SCOPE:
        return
    if str(actual) != expected:
        raise PermissionDenied("Staff session origin does not match.")


class RefreshView(TokenRefreshView):
    @extend_schema(
        tags=["Auth"],
        summary="Refresh access token",
        auth=[],
        request=None,
        responses={
            200: RefreshResponseSerializer,
            401: OpenApiResponse(description="Missing, invalid, or replayed refresh token."),
            403: OpenApiResponse(description="CSRF check failed or account restricted."),
        },
    )
    def post(self, request, *args, **kwargs):
        cookie = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE)
        try:
            assert_csrf(
                request, surface=_refresh_surface(cookie) if cookie else None
            )
            if cookie:
                _assert_staff_refresh_scope(request, cookie)
        except APIException:
            audit_events.record_auth_event(
                None, "auth.refresh_rejected", meta={"reason": "csrf"}
            )
            raise
        if not cookie:
            audit_events.record_auth_event(
                None, "auth.refresh_rejected", meta={"reason": "missing_cookie"}
            )
            raise InvalidToken("No refresh cookie.")
        if not _refresh_user_is_active(cookie):
            actor = audit_events.user_from_refresh_token(cookie)
            audit_events.record_auth_event(
                actor,
                "auth.refresh_rejected",
                target=actor,
                meta={"reason": "restricted_account"},
            )
            response = Response({"detail": "Account access is restricted."}, status=403)
            clear_refresh_cookies(response)
            return response
        serializer = self.get_serializer(data={"refresh": cookie})
        try:
            serializer.is_valid(raise_exception=True)
        except InvalidToken:
            actor = audit_events.user_from_refresh_token(cookie)
            audit_events.record_auth_event(
                actor,
                "auth.refresh_rejected",
                target=actor,
                meta={"reason": "invalid_token"},
            )
            raise
        except TokenError as exc:
            actor = audit_events.user_from_refresh_token(cookie)
            audit_events.record_auth_event(
                actor,
                "auth.refresh_rejected",
                target=actor,
                meta={"reason": "invalid_token"},
            )
            raise InvalidToken(str(exc)) from exc
        data = serializer.validated_data
        response = Response({"access": data["access"]})
        new_refresh = data.get("refresh")
        if new_refresh:
            set_refresh_cookies(response, new_refresh, request)
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        summary="Log out and clear refresh cookie",
        auth=[],
        request=None,
        responses={
            200: LogoutResponseSerializer,
            401: OpenApiResponse(description="Refresh token could not be blacklisted."),
            403: OpenApiResponse(description="CSRF check failed."),
        },
    )
    def post(self, request, *args, **kwargs):
        cookie = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE)
        assert_csrf(request, surface=_refresh_surface(cookie) if cookie else None)
        if cookie:
            _assert_staff_refresh_scope(request, cookie)
        actor = audit_events.user_from_refresh_token(cookie)
        if cookie:
            try:
                RefreshToken(cookie).blacklist()
            except TokenError:
                pass
        audit_events.record_auth_event(
            actor,
            "auth.logout",
            target=actor,
            meta={"had_refresh_cookie": bool(cookie)},
        )
        response = Response({"detail": "Logged out."})
        clear_refresh_cookies(response)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        summary="Get current staff profile",
        request=None,
        responses={
            200: UserPayloadSerializer,
            400: OpenApiResponse(description="Invalid request."),
            401: OpenApiResponse(description="Authentication credentials were not provided."),
            403: OpenApiResponse(description="Permission denied."),
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def get(self, request, *args, **kwargs):
        return Response(user_payload(request.user, request=request))
