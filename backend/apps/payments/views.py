import logging

from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.makerspaces.models import Makerspace
from apps.payments.models import MakerspacePaymentSettings
from apps.payments.providers import WebhookVerificationError, get_provider
from apps.payments.resolution import resolve_payment_source
from apps.payments.services import apply_razorpay_webhook_event, apply_webhook_event
from apps.payments.stripe_client import PaymentsUnavailable, StripeWebhookSignatureError, construct_event

logger = logging.getLogger(__name__)


class StripeWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(tags=["Payments"], summary="Receive a makerspace Stripe webhook", description="Verifies the Stripe signature using request.body and the addressed makerspace's webhook secret before applying an idempotent event.", auth=[], request=None, responses={200: OpenApiResponse(description="Verified event acknowledged."), 400: OpenApiResponse(description="Invalid signature, payload, or configuration."), 404: OpenApiResponse(description="Makerspace was not found.")})
    def post(self, request, public_code):
        # The public code only addresses the tenant; its unchanged per-space secret
        # authenticates the callback. An archived row must remain addressable because
        # the provider has already taken the money and ProcessedStripeEvent keeps
        # settlement idempotent, while a purged row still misses this lookup naturally.
        makerspace = Makerspace.objects.filter(public_code__iexact=public_code).first()
        if makerspace is None:
            logger.warning("stripe_webhook_unknown_makerspace", extra={"public_code": public_code})
            return Response({"detail": "Makerspace not found."}, status=status.HTTP_404_NOT_FOUND)
        payment_settings = MakerspacePaymentSettings.for_makerspace(makerspace)
        if not payment_settings.raw_credentials_configured:
            logger.warning("stripe_webhook_unconfigured", extra={"makerspace_id": makerspace.id})
            return Response({"detail": "Payments are not configured."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            event = construct_event(request.body, request.headers.get("Stripe-Signature", ""), payment_settings.get_stripe_webhook_secret())
        except (
            StripeWebhookSignatureError,
            PaymentsUnavailable,
            ImproperlyConfigured,
            InvalidToken,
            ValueError,
        ):
            logger.warning("stripe_webhook_rejected", extra={"makerspace_id": makerspace.id})
            return Response({"detail": "Invalid Stripe webhook signature."}, status=status.HTTP_400_BAD_REQUEST)
        apply_webhook_event(
            makerspace, event, provider="raw"
        )
        return Response({"detail": "Verified."}, status=status.HTTP_200_OK)


class RazorpayWebhookView(APIView):
    """Verify a Razorpay signature over the RAW body, then settle idempotently.

    Deliberately mirrors StripeWebhookView rather than sharing a base class: the two
    endpoints are separately addressable in each vendor's dashboard, and a shared view
    that dispatched on a body field would decide which secret to verify against using
    data from the very request it has not verified yet.

    Like the Stripe endpoint it settles regardless of the live capability toggle -- a
    real charge must never be stranded because someone unticked a feature between
    checkout and callback. It is also NOT gated by the `payments` module for the same
    reason: uninstalling stops new charges, it does not abandon money already taken.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Payments"],
        summary="Receive a makerspace Razorpay webhook",
        description=(
            "Verifies the X-Razorpay-Signature HMAC over request.body using the "
            "addressed makerspace's webhook secret before applying an idempotent event."
        ),
        auth=[],
        request=None,
        responses={
            200: OpenApiResponse(description="Verified event acknowledged."),
            400: OpenApiResponse(description="Invalid signature, payload, or configuration."),
            404: OpenApiResponse(description="Makerspace was not found."),
        },
    )
    def post(self, request, public_code):
        # The public code only addresses the tenant; its unchanged per-space secret
        # authenticates the callback. An archived row must remain addressable because
        # the provider has already taken the money and ProcessedStripeEvent keeps
        # settlement idempotent, while a purged row still misses this lookup naturally.
        makerspace = Makerspace.objects.filter(public_code__iexact=public_code).first()
        if makerspace is None:
            logger.warning("razorpay_webhook_unknown_makerspace", extra={"public_code": public_code})
            return Response({"detail": "Makerspace not found."}, status=status.HTTP_404_NOT_FOUND)
        settings_row = MakerspacePaymentSettings.for_makerspace(makerspace)
        if settings_row.provider != "razorpay":
            # A Razorpay callback for a Stripe space is either a misconfiguration or a
            # probe. Either way there is no secret to verify it with.
            logger.warning("razorpay_webhook_wrong_provider", extra={"makerspace_id": makerspace.id})
            return Response({"detail": "Razorpay is not configured."}, status=status.HTTP_400_BAD_REQUEST)
        source = resolve_payment_source(makerspace)
        if source is None:
            logger.warning("razorpay_webhook_unconfigured", extra={"makerspace_id": makerspace.id})
            return Response({"detail": "Payments are not configured."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            event = get_provider("razorpay").verify_webhook(
                source, payload=request.body, headers=request.headers
            )
        except (WebhookVerificationError, ImproperlyConfigured, InvalidToken, ValueError):
            logger.warning("razorpay_webhook_rejected", extra={"makerspace_id": makerspace.id})
            return Response(
                {"detail": "Invalid Razorpay webhook signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        apply_razorpay_webhook_event(makerspace, event)
        # 200 even for an event we chose not to act on: Razorpay retries a non-2xx, and
        # retrying an event that is correctly ignored achieves nothing but load.
        return Response({"detail": "Verified."}, status=status.HTTP_200_OK)
