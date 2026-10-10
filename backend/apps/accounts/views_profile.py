"""Browser login, refresh, logout, and current-user endpoints."""

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from apps.accounts import audit_events
from apps.accounts.auth_cookies import (
    assert_csrf,
    clear_refresh_cookies,
    set_refresh_cookies,
)
from apps.accounts.claim_tokens import ClaimRefreshToken, rotate_claim_refresh
from apps.accounts.schemas_auth import (
    LoginRequestSerializer,
    LoginResponseSerializer,
    LogoutResponseSerializer,
    RefreshResponseSerializer,
    UserPayloadSerializer,
)
from apps.accounts.serializers import LoginSerializer, SpaceWorksTokenRefreshSerializer, user_payload
from apps.accounts.tokens import SpaceWorksRefreshToken


from .views_refresh import _assert_staff_refresh_scope, _refresh_surface

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
                # A claim refresh will not decode as a plain RefreshToken, and logout
                # must still revoke it.
                try:
                    refresh = ClaimRefreshToken(cookie)
                except TokenError:
                    refresh = SpaceWorksRefreshToken(cookie)
                refresh.blacklist()
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
