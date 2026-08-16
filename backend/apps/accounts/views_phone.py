"""Phone OTP endpoints: sign in with a number, and link one to your account.

Every response on the login path is deliberately uniform -- see services_phone for
the enumeration reasoning. The only status that distinguishes anything is 404 when
SMS is not configured at all, which is deployment state, not account state.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import audit_events
from apps.accounts.auth_cookies import set_refresh_cookies
from apps.accounts.authentication import SpaceWorksJWTAuthentication
from apps.accounts.serializers import user_payload
from apps.accounts.serializers_phone import (
    PhoneConfirmSerializer,
    PhoneStartResponseSerializer,
    PhoneStartSerializer,
    PhoneStatusSerializer,
)
from apps.accounts.services_phone import (
    GENERIC_START_ACK,
    ChallengeCooldown,
    SmsUnavailable,
    confirm_link,
    confirm_login,
    start_link,
    start_login,
)
from apps.accounts.throttles import (
    PhoneConfirmNumberThrottle,
    PhoneLoginConfirmThrottle,
    PhoneOtpNumberThrottle,
    PhoneOtpRequestThrottle,
)

SMS_UNAVAILABLE = {"detail": "Phone sign-in is not available on this deployment."}


def _phone_login_available():
    """Phone sign-in needs both the member ecosystem and its own method switch.

    Phone sign-in is a MEMBER credential, so it goes with the member ecosystem.

    Answered before the number is even parsed. The response is the same 404 an
    unconfigured deployment returns, and deliberately so: both are deployment state, not
    account state, and the enumeration contract this endpoint keeps is about not
    disclosing whether a *number* is known -- never about hiding how the box is set up.
    """
    from apps.accounts.login_methods import phone_login_enabled
    from apps.accounts.member_identity import member_login_allowed

    return member_login_allowed() and phone_login_enabled()


class PhoneLoginStartView(APIView):
    """Request a login code for an already-verified number."""

    # Anonymous without a header; a presented claim token must still be evaluated by
    # the Refused route policy before this endpoint can mint another credential.
    authentication_classes = [SpaceWorksJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [PhoneOtpRequestThrottle, PhoneOtpNumberThrottle]

    @extend_schema(
        tags=["Auth"],
        summary="Request a phone sign-in code",
        auth=[],
        request=PhoneStartSerializer,
        responses={
            200: PhoneStartResponseSerializer,
            400: OpenApiResponse(description="Invalid request."),
            404: OpenApiResponse(description="Phone sign-in is not configured."),
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def post(self, request):
        if not _phone_login_available():
            return Response(SMS_UNAVAILABLE, status=status.HTTP_404_NOT_FOUND)
        serializer = PhoneStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            start_login(serializer.validated_data["phone"])
        except SmsUnavailable:
            return Response(SMS_UNAVAILABLE, status=status.HTTP_404_NOT_FOUND)
        # Always the same body, always 200 -- whether the number is unknown, malformed,
        # suspended, or on cooldown.
        return Response({"detail": GENERIC_START_ACK})


class PhoneLoginConfirmView(APIView):
    """Exchange a valid code for a MEMBER session. Never mints a staff session."""

    authentication_classes = [SpaceWorksJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [PhoneLoginConfirmThrottle, PhoneConfirmNumberThrottle]

    @extend_schema(
        tags=["Auth"],
        summary="Sign in with a phone code",
        auth=[],
        request=PhoneConfirmSerializer,
        responses={
            200: OpenApiResponse(description="Member session issued."),
            400: OpenApiResponse(description="Invalid or expired code."),
            404: OpenApiResponse(description="Phone sign-in is not configured."),
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def post(self, request):
        # Re-checked here, not just on start: a code issued before the module was
        # switched off must not still mint a session after it.
        if not _phone_login_available():
            return Response(SMS_UNAVAILABLE, status=status.HTTP_404_NOT_FOUND)
        serializer = PhoneConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = confirm_login(data["phone"], data["code"])

        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        # Hardcoded "member", never derived from the request. An SMS code is the weakest
        # factor here (SIM swap, number recycling) and staff surfaces reject this claim.
        refresh["surface"] = "member"
        audit_events.record_auth_event(
            user,
            "auth.phone_login_succeeded",
            target=user,
            meta={"phone_hash": audit_events.fingerprint(user.phone_e164)},
        )
        response = Response(
            {
                "access": str(refresh.access_token),
                "user": user_payload(user, request=request),
            }
        )
        set_refresh_cookies(response, str(refresh), request)
        return response


class PhoneLinkStartView(APIView):
    """Send a code to a number the caller wants to attach to their own account."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [PhoneOtpNumberThrottle]

    @extend_schema(
        tags=["Auth"],
        summary="Request a code to link a phone number",
        request=PhoneStartSerializer,
        responses={
            200: PhoneStartResponseSerializer,
            400: OpenApiResponse(description="Invalid or already-linked number."),
            404: OpenApiResponse(description="Phone sign-in is not configured."),
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def post(self, request):
        serializer = PhoneStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            start_link(request.user, serializer.validated_data["phone"])
        except SmsUnavailable:
            return Response(SMS_UNAVAILABLE, status=status.HTTP_404_NOT_FOUND)
        except ChallengeCooldown:
            return Response(
                {"detail": "A code was just sent. Try again in a minute."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return Response({"detail": "Verification code sent."})


class PhoneLinkConfirmView(APIView):
    """Attach the verified number to the caller's account."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [PhoneConfirmNumberThrottle]

    @extend_schema(
        tags=["Auth"],
        summary="Confirm and link a phone number",
        request=PhoneConfirmSerializer,
        responses={
            200: PhoneStatusSerializer,
            400: OpenApiResponse(description="Invalid or expired code."),
            429: OpenApiResponse(description="Request throttled."),
        },
    )
    def post(self, request):
        serializer = PhoneConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = confirm_link(request.user, data["phone"], data["code"])
        return Response({"phone_e164": user.phone_e164, "verified": True})


class PhoneUnlinkView(APIView):
    """Detach the number. Always safe: every account keeps an email credential."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        summary="Unlink the phone number",
        responses={200: PhoneStatusSerializer},
    )
    def delete(self, request):
        user = request.user
        if user.phone_e164:
            audit_events.record_auth_event(
                user,
                "member.phone_unlinked",
                target=user,
                meta={"phone_hash": audit_events.fingerprint(user.phone_e164)},
            )
            user.phone_e164 = ""
            # save() clears phone_verified_at via the model hook, but name it explicitly
            # so update_fields cannot drop the write.
            user.phone_verified_at = None
            user.save(update_fields=["phone_e164", "phone_verified_at"])
        return Response({"phone_e164": "", "verified": False})
