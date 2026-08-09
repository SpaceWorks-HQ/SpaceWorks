from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.serializers_registration import (
    EmailVerificationConfirmSerializer,
    MemberSignUpSerializer,
)
from apps.accounts.services_registration import (
    GENERIC_CONFIRM_ERROR,
    ChallengeCooldown,
    confirm_challenge,
    issue_challenge,
    register_member,
)
from apps.accounts.throttles import (
    MemberSignUpEmailThrottle,
    MemberVerificationEmailThrottle,
)

GenericAckSerializer = inline_serializer(
    name="MemberVerificationAck", fields={"detail": serializers.CharField()}
)


def _member_accounts_enabled():
    """Whether this deployment offers member self sign-up.

    Sign-up resolves before any makerspace is selected, so the `accounts` module is
    read at deployment level -- see `makerspaces.deployment_modules`. Fails OPEN on a
    lookup error, matching every other capability read on this path: a broken check
    must not lock people out of registering.

    STAFF sign-in is untouched by this. It is core RBAC, and a deployment that could
    switch off its own staff logins could not be administered.
    """
    try:
        from apps.makerspaces.deployment_modules import member_accounts_enabled

        return member_accounts_enabled()
    except Exception:  # pragma: no cover - defensive, mirrors the other capability reads
        return True


class MemberSignUpView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle, MemberSignUpEmailThrottle]
    throttle_scope = "member_sign_up"

    @extend_schema(
        tags=["Auth"], auth=[], request=MemberSignUpSerializer,
        responses={
            200: GenericAckSerializer, 400: OpenApiResponse(description="Invalid details."),
            401: OpenApiResponse(description="Authentication failed."),
            403: OpenApiResponse(description="Permission denied."),
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def post(self, request):
        if request.data.get("website"):
            return _generic_ack()
        if not _member_accounts_enabled():
            # The same generic ack the honeypot returns. A distinct error here would
            # tell an unauthenticated caller how this deployment is configured, and the
            # endpoint's whole contract is that it never discloses anything.
            return _generic_ack()
        serializer = MemberSignUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        register_member(
            display_name=data["display_name"],
            email=data["email"],
            phone=data["phone"],
            password=data["password"],
        )
        return _generic_ack()


class EmailVerificationResendView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle, MemberVerificationEmailThrottle]
    throttle_scope = "email_verification_resend"

    @extend_schema(
        tags=["Auth"], request=None,
        responses={
            200: GenericAckSerializer, 400: OpenApiResponse(description="Invalid request."),
            401: OpenApiResponse(description="Authentication credentials were not provided."),
            403: OpenApiResponse(description="Permission denied."),
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def post(self, request):
        if request.user.email_verified_at is None and request.user.email:
            try:
                issue_challenge(request.user)
            except ChallengeCooldown:
                pass
        return _generic_ack()


class EmailVerificationConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_verification_confirm"

    @extend_schema(
        tags=["Auth"], request=EmailVerificationConfirmSerializer,
        responses={
            200: GenericAckSerializer, 400: OpenApiResponse(description=GENERIC_CONFIRM_ERROR),
            401: OpenApiResponse(description="Authentication credentials were not provided."),
            403: OpenApiResponse(description="Permission denied."),
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def post(self, request):
        serializer = EmailVerificationConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            raise serializers.ValidationError({"detail": GENERIC_CONFIRM_ERROR})
        confirm_challenge(request.user, **serializer.validated_data)
        return Response({"detail": "Email verified."})


def _generic_ack():
    return Response({"detail": "If the details are valid, a verification email has been sent."})
