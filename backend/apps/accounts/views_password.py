"""Password change and anonymous account-recovery endpoints."""

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from drf_spectacular.utils import (
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.principal_guards import is_anonymous_requester
from apps.accounts.password_reset_crypto import normalize_email
from apps.accounts.serializers_password_reset import (
    ChangePasswordResponseSerializer,
    ChangePasswordSerializer,
    ForgotPasswordRequestSerializer,
    LegacyResetPasswordConfirmSerializer,
    OtpResetPasswordConfirmSerializer,
    PasswordResetAcknowledgementSerializer,
    PasswordResetFailureSerializer,
    PasswordUpdatedSerializer,
    PasswordValidationFailureSerializer,
    RecoveryUnavailableSerializer,
    ResetPasswordConfirmSerializer,
)
from apps.accounts.services_password_reset import (
    GENERIC_CONFIRM_ERROR,
    PasswordResetCooldown,
    confirm_password_reset,
    request_password_reset,
    validate_recovery_password,
)
from apps.accounts.services_tokens import blacklist_outstanding_tokens
from apps.accounts.throttles import (
    PasswordResetConfirmEmailThrottle,
    PasswordResetEmailThrottle,
)
from apps.audit import services as audit
from apps.integrations.email import email_enabled


CONFIRM_REQUEST_SCHEMA = PolymorphicProxySerializer(
    component_name="ResetPasswordConfirmRequest",
    serializers=[
        OtpResetPasswordConfirmSerializer,
        LegacyResetPasswordConfirmSerializer,
    ],
    resource_type_field_name=None,
)
CONFIRM_ERROR_SCHEMA = PolymorphicProxySerializer(
    component_name="ResetPasswordConfirmError",
    serializers=[
        PasswordResetFailureSerializer,
        PasswordValidationFailureSerializer,
    ],
    resource_type_field_name=None,
)

GENERIC_ACKNOWLEDGEMENT = {
    "detail": "If an account exists for that email, a reset link has been sent."
}
RECOVERY_UNAVAILABLE = {
    "detail": "Password recovery is unavailable. Contact your makerspace staff.",
    "code": "recovery_unavailable",
}


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

        if (
            user.is_walk_in
            or is_anonymous_requester(user)
            or not user.check_password(current_password)
        ):
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
            raise serializers.ValidationError(
                {"new_password": list(exc.messages)}
            ) from exc

        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=user.pk)
            if (
                locked.is_walk_in
                or is_anonymous_requester(locked)
                or not locked.check_password(current_password)
            ):
                raise serializers.ValidationError(
                    {"current_password": "Current password is incorrect."}
                )
            locked.set_password(new_password)
            locked.must_change_password = False
            locked.save(update_fields=["password", "must_change_password"])
        blacklist_outstanding_tokens(locked)
        audit.record(locked, "user.password_changed", target=locked)
        return Response({"detail": "Password updated."})


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle, PasswordResetEmailThrottle]
    throttle_scope = "password_reset_request"

    @extend_schema(
        tags=["Auth"],
        summary="Request an emailed password reset code",
        auth=[],
        request=ForgotPasswordRequestSerializer,
        responses={
            200: PasswordResetAcknowledgementSerializer,
            400: OpenApiResponse(description="Invalid request."),
            429: OpenApiResponse(description="Request throttled."),
            503: RecoveryUnavailableSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        # This deployment-level gate deliberately precedes payload validation and every
        # account-independent envelope write. It reveals only the same mail capability
        # already published by /api/v1/config.
        if not email_enabled():
            return Response(
                RECOVERY_UNAVAILABLE, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        serializer = ForgotPasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            request_password_reset(serializer.validated_data["email"])
        except PasswordResetCooldown:
            # A per-account 429 would turn the resend budget into an enumeration oracle.
            pass
        return Response(GENERIC_ACKNOWLEDGEMENT)


class ResetPasswordConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle, PasswordResetConfirmEmailThrottle]
    throttle_scope = "password_reset_confirm"

    @extend_schema(
        tags=["Auth"],
        summary="Confirm an OTP or coexisting legacy password reset link",
        auth=[],
        request=CONFIRM_REQUEST_SCHEMA,
        responses={
            200: PasswordUpdatedSerializer,
            400: CONFIRM_ERROR_SCHEMA,
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = ResetPasswordConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["method"] == "otp":
            confirm_password_reset(
                data["email"], data["code"], data["new_password"]
            )
        else:
            # Removal condition: last time old links could be issued +
            # PASSWORD_RESET_TIMEOUT. A release count is not a safe clock.
            _confirm_legacy_link(data["uid"], data["token"], data["new_password"])
        return Response({"detail": "Password updated."})


def _confirm_legacy_link(uid, token, new_password):
    failure = None
    password_failure = None
    changed_user = None
    try:
        user_pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.filter(pk=user_pk).first()
    except (ValueError, TypeError, OverflowError):
        user = None
    verified_email = _verified_legacy_email(user, token)
    if verified_email is None:
        raise _generic_confirmation_failure()

    with transaction.atomic():
        locked = User.objects.select_for_update().filter(pk=user.pk).first()
        if _verified_legacy_email(locked, token, expected_email=verified_email) is None:
            failure = _generic_confirmation_failure()
        else:
            try:
                validate_recovery_password(new_password, locked)
            except DjangoValidationError as exc:
                password_failure = serializers.ValidationError(
                    {"new_password": list(exc.messages)}
                )
            else:
                locked.set_password(new_password)
                locked.must_change_password = False
                locked.save(update_fields=["password", "must_change_password"])
                audit.record(
                    locked,
                    "user.password_reset_via_email",
                    target=locked,
                    meta={"method": "link"},
                )
                changed_user = locked

    if failure is not None:
        raise failure
    if password_failure is not None:
        raise password_failure
    blacklist_outstanding_tokens(changed_user)


def _verified_legacy_email(user, token, *, expected_email=None):
    if not (
        user
        and user.is_active
        and user.access_status == User.AccessStatus.ACTIVE
        and not user.is_walk_in
        and not is_anonymous_requester(user)
    ):
        return None
    try:
        normalized = normalize_email(user.email)
    except ValueError:
        return None
    if expected_email is not None and normalized != expected_email:
        return None
    return normalized if default_token_generator.check_token(user, token) else None


def _generic_confirmation_failure():
    return serializers.ValidationError({"detail": GENERIC_CONFIRM_ERROR})
