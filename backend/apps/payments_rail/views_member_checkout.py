"""Raising an online checkout for a member's own charge.

Split from `apps.payments.views_member` when the ledger and the rail became separately
tombstonable. The history and archived-discovery surfaces stayed core -- a member must
always be able to see what they owe and what they have paid -- while creating a provider
checkout is only meaningful on a deployment that ships the rail at all.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hardware_requests.exceptions import ErrorSerializer
from apps.payments import stripe_client
from apps.payments.availability import online_payments_enabled_for
from apps.payments.member_scope import member_payment_queryset
from apps.payments.models import Payment
from apps.payments.serializers import CheckoutUrlSerializer
from apps.payments.services import PaymentRailConflict, create_checkout_url


class MemberPaymentCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Payments"],
        summary="Generate a Checkout link for the caller's pending payment",
        request=None,
        responses={200: CheckoutUrlSerializer, 404: OpenApiResponse(ErrorSerializer), 503: OpenApiResponse(ErrorSerializer)},
    )
    def post(self, request, makerspace_id, payment_id):
        payment = member_payment_queryset(request.user, makerspace_id).filter(
            pk=payment_id,
            status=Payment.Status.PENDING,
        ).first()
        if payment is None:
            raise NotFound()
        if payment.stripe_checkout_url:
            return Response({"checkout_url": payment.stripe_checkout_url})
        # A charge can exist with no rail behind it (cash-only space, or the rail switched
        # off after the debt was raised). Refuse rather than mint a link the space cannot
        # honour; the member settles this one at the desk.
        if not online_payments_enabled_for(payment):
            # Returned directly, not raised: the handler below that converts provider
            # failures into a structured 503 only wraps the create_checkout_url call, so
            # raising here escaped it and DRF answered 500 for an ordinary cash-only
            # charge.
            return Response(
                {
                    "detail": "Online payment is not available for this charge.",
                    "code": "payments_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            checkout_url = create_checkout_url(payment.pk, actor=request.user)
        except PaymentRailConflict:
            return Response(
                {
                    'detail': 'The payment already uses a different online payment rail.',
                    'code': 'payment_rail_conflict',
                },
                status=status.HTTP_409_CONFLICT,
            )
        except Exception:
            return Response({"detail": "Payments are temporarily unavailable.", "code": "payments_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not checkout_url:
            raise NotFound()
        return Response({"checkout_url": checkout_url})
