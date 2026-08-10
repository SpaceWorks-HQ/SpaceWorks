import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts import audit_events
from apps.accounts.login_methods import password_login_enabled
from apps.accounts.auth_cookies import assert_csrf, clear_refresh_cookies, set_refresh_cookies
from apps.accounts.models import User
from apps.accounts.serializers import LoginSerializer, user_payload
from apps.accounts.services_tokens import blacklist_outstanding_tokens
from apps.accounts.throttles import PasswordResetEmailThrottle
from apps.audit import services as audit
from apps.integrations.email import send_password_reset_email
from apps.openapi import LOGIN_EXAMPLE


logger = logging.getLogger(__name__)

AuthMembershipSerializer = inline_serializer(
    name="AuthMembership",
    fields={
        "id": serializers.IntegerField(),
        "slug": serializers.CharField(),
        "role": serializers.CharField(),
        "role_id": serializers.IntegerField(allow_null=True),
        "role_name": serializers.CharField(),
        "role_slug": serializers.CharField(),
        "actions": serializers.ListField(child=serializers.CharField()),
        "can_refer": serializers.BooleanField(),
        "can_verify": serializers.BooleanField(),
        "verified_at": serializers.DateTimeField(allow_null=True),
        "referrals_enabled": serializers.BooleanField(),
    },
)
UserPayloadSerializer = inline_serializer(
    name="AuthUserPayload",
    fields={
        "id": serializers.IntegerField(),
        "username": serializers.CharField(),
        "email": serializers.EmailField(),
        "display_name": serializers.CharField(),
        "phone": serializers.CharField(),
        "email_verified": serializers.BooleanField(),
        "role": serializers.CharField(),
        "is_superuser": serializers.BooleanField(),
        "must_change_password": serializers.BooleanField(),
        "makerspaces": serializers.ListField(child=AuthMembershipSerializer),
    },
)
LoginRequestSerializer = inline_serializer(
    name="LoginRequest",
    fields={
        "username": serializers.CharField(),
        "password": serializers.CharField(write_only=True),
    },
)
LoginResponseSerializer = inline_serializer(
    name="LoginResponse",
    fields={
        "access": serializers.CharField(),
        "user": UserPayloadSerializer,
    },
)
RefreshResponseSerializer = inline_serializer(name="RefreshResponse", fields={"access": serializers.CharField()})
LogoutResponseSerializer = inline_serializer(name="LogoutResponse", fields={"detail": serializers.CharField()})
ChangePasswordResponseSerializer = inline_serializer(name="ChangePasswordResponse", fields={"detail": serializers.CharField()})


class ForgotPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)


class LoginView(TokenObtainPairView):
    # Explicit under deny-by-default (DEFAULT_PERMISSION_CLASSES=IsAuthenticated):
    # obtaining a token must be open. RefreshView inherits simplejwt's AllowAny.
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
        # Answered before the credentials are even parsed. Password sign-in being off is
        # deployment state, so it is a 403 rather than the 401 a wrong password gets --
        # telling the caller "not this way" instead of "not you", which is the difference
        # between a login screen that can explain itself and one that cannot.
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
        return True  # invalid token: let the serializer reject it as 401, not 403
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
            )  # header presence + surface-specific exact origin
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
        if not _refresh_user_is_active(cookie):  # review fix #5
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
    permission_classes = [AllowAny]  # cookie-based; protected by assert_csrf below

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
        assert_csrf(
            request, surface=_refresh_surface(cookie) if cookie else None
        )  # logout must not be CSRF-able
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


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        summary="Change current user's password",
        request=ChangePasswordSerializer,
        responses={
            200: ChangePasswordResponseSerializer,
            400: OpenApiResponse(description="Password validation failed."),
            401: OpenApiResponse(description="Authentication credentials were not provided."),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        current_password = serializer.validated_data["current_password"]
        new_password = serializer.validated_data["new_password"]
        user = request.user

        # Defence in depth: this becomes load-bearing the moment any path gives a
        # walk-in a usable password.
        if user.is_walk_in:
            raise serializers.ValidationError(
                {"current_password": "Current password is incorrect."}
            )
        if not user.check_password(current_password):
            raise serializers.ValidationError(
                {"current_password": "Current password is incorrect."}
            )
        if new_password == current_password:
            raise serializers.ValidationError(
                {"new_password": "New password must be different from the current password."}
            )
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc

        with transaction.atomic():
            # Re-read under a row lock and repeat the guard next to the write, as every
            # other credential writer on this seam does. The check above ran against
            # `request.user`, built from a JWT that may predate migration 0015 marking
            # this record: without the lock, a request that started while `is_walk_in`
            # was still false waits here and then writes a fresh usable password AFTER
            # the migration committed the unusable one, undoing the revocation for
            # exactly the accounts it exists for.
            locked = User.objects.select_for_update().get(pk=user.pk)
            if locked.is_walk_in:
                raise serializers.ValidationError(
                    {"current_password": "Current password is incorrect."}
                )
            locked.set_password(new_password)
            locked.must_change_password = False
            locked.save(update_fields=["password", "must_change_password"])
        user = locked
        blacklist_outstanding_tokens(user)
        audit.record(user, "user.password_changed", target=user)
        return Response({"detail": "Password updated."})


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle, PasswordResetEmailThrottle]
    throttle_scope = "password_reset_request"

    @extend_schema(
        tags=["Auth"],
        summary="Request a password reset email",
        auth=[],
        request=ForgotPasswordRequestSerializer,
        responses={200: OpenApiResponse(description="Generic acknowledgement.")},
    )
    def post(self, request, *args, **kwargs):
        serializer = ForgotPasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        user = None
        email_sent = False
        try:
            user = (
                User.objects.filter(
                    email__iexact=email,
                    is_active=True,
                    access_status=User.AccessStatus.ACTIVE,
                )
                # A walk-in is a person record, not an account. Without this, whoever
                # holds the mailbox staff typed at the counter could reset "their"
                # password into existence and sign in -- turning a no-login record into a
                # real account and walking straight past disabled self-registration.
                # The response stays the same generic ack, so this discloses nothing.
                .exclude(is_walk_in=True)
                .exclude(email="")
                .first()
            )
            if user:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                base = settings.PUBLIC_APP_BASE_URL or ""
                reset_url = f"{base}/reset-password?uid={uid}&token={token}"
                send_password_reset_email(user.email, reset_url)
                email_sent = True
        except Exception:
            logger.exception("Password reset request failed for an email")
        audit_events.record_auth_event(
            user,
            "auth.password_reset_requested",
            target=user,
            meta={
                "email_hash": audit_events.fingerprint(email),
                "email_sent": email_sent,
            },
        )
        return Response(
            {"detail": "If an account exists for that email, a reset link has been sent."}
        )


class ResetPasswordConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_confirm"

    @extend_schema(
        tags=["Auth"],
        summary="Confirm a password reset",
        auth=[],
        request=ResetPasswordConfirmSerializer,
        responses={
            200: OpenApiResponse(description="Password updated."),
            400: OpenApiResponse(description="Invalid/expired token or password."),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = ResetPasswordConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        bad = serializers.ValidationError({"detail": "Invalid or expired reset link."})
        try:
            uid = force_str(urlsafe_base64_decode(data["uid"]))
            user = User.objects.filter(pk=uid).first()
        except (ValueError, TypeError, OverflowError):
            user = None
        if user is None:
            raise bad
        if not (user.is_active and user.access_status == User.AccessStatus.ACTIVE):
            raise bad
        # Checked here as well as on the request side: a link issued before the record
        # was marked, or minted any other way, must still not turn a person record into
        # an account. Same generic error, so it discloses nothing.
        if user.is_walk_in:
            raise bad
        if not default_token_generator.check_token(user, data["token"]):
            raise bad
        try:
            validate_password(data["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc

        with transaction.atomic():
            # Close the stale-read interleaving where the walk-in migration marks this
            # user after the check above but before this password write.
            user = User.objects.select_for_update().get(pk=user.pk)
            if user.is_walk_in:
                raise bad
            user.set_password(data["new_password"])
            user.must_change_password = False
            user.save(update_fields=["password", "must_change_password"])
        blacklist_outstanding_tokens(user)
        audit.record(user, "user.password_reset_via_email", target=user)
        return Response({"detail": "Password updated."})
