"""Browser login, refresh, logout, and current-user endpoints."""

from collections.abc import Mapping

from drf_spectacular.utils import OpenApiResponse, PolymorphicProxySerializer, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.accounts import audit_events
from apps.accounts.auth_cookies import (
    clear_refresh_cookies,
    set_refresh_cookies,
)
from apps.accounts.login_methods import password_login_enabled
from apps.accounts.authentication import SpaceWorksJWTAuthentication
from apps.accounts.schemas_auth import (
    LoginRequestSerializer,
    LoginResponseSerializer,
)
from apps.accounts.serializers import LoginSerializer
from apps.accounts.serializers_mfa import MFAChallengeResponseSerializer
from apps.openapi import LOGIN_EXAMPLE


class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    serializer_class = LoginSerializer
    # SimpleJWT's token view disables authentication entirely. Keep anonymous login,
    # but still inspect a presented claim token so the central Refused matrix is real.
    authentication_classes = [SpaceWorksJWTAuthentication]

    @extend_schema(
        tags=["Auth"],
        summary="Log in with a password",
        auth=[],
        request=LoginRequestSerializer,
        responses={
            200: PolymorphicProxySerializer(component_name="PasswordLoginResult", serializers=[LoginResponseSerializer, MFAChallengeResponseSerializer], resource_type_field_name=None),
            400: OpenApiResponse(description="Invalid request."),
            401: OpenApiResponse(description="Invalid credentials or inactive account."),
            403: OpenApiResponse(description="Account access is restricted."),
            429: OpenApiResponse(description="Request throttled."),
            503: OpenApiResponse(description="Authentication write boundary unavailable."),
        },
        examples=[LOGIN_EXAMPLE],
    )
    def post(self, request, *args, **kwargs):
        if not password_login_enabled():
            return Response(
                {"detail": "Password sign-in is not available on this deployment."},
                status=403,
            )
        username = request.data.get("username", "") if isinstance(request.data, Mapping) else ""
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
        if data.get("mfa_required"):
            response = Response(data)
            clear_refresh_cookies(response)
            response["Cache-Control"] = "no-store"
            return response
        refresh = data.pop("refresh")
        audit_events.record_auth_event(
            serializer.user,
            "auth.login_succeeded",
            target=serializer.user,
            meta={"username_hash": audit_events.fingerprint(username)},
        )
        response = Response({"access": data["access"], "surface": data["surface"], "user": data["user"]})
        set_refresh_cookies(response, refresh, request)
        return response


