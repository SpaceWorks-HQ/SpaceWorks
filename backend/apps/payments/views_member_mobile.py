from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.views_device import IsDeviceAccessToken
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.origin_scope import require_native_selected_makerspace
from apps.payments import stripe_client
from apps.payments.member_scope import member_payment_queryset
from apps.payments.models import Payment
from apps.payments.serializers_mobile import MobilePaymentIntentResponseSerializer
from apps.payments.services import PaymentRailConflict
from apps.payments.services_mobile import create_mobile_intent


class MemberMobilePaymentIntentView(APIView):
    permission_classes = [IsDeviceAccessToken]

    @extend_schema(
        tags=['Payments'],
        summary='Create or retrieve a native mobile payment intent',
        request=None,
        responses={
            200: MobilePaymentIntentResponseSerializer,
            401: OpenApiResponse(ErrorSerializer),
            403: OpenApiResponse(ErrorSerializer),
            404: OpenApiResponse(ErrorSerializer),
            409: OpenApiResponse(ErrorSerializer),
            503: OpenApiResponse(ErrorSerializer),
        },
    )
    def post(self, request, makerspace_id, payment_id):
        require_native_selected_makerspace(request, makerspace_id)
        # Same scope as the web surfaces: an event charge raised by a partner host is
        # payable from the member area the member reached it through, or the charge exists
        # with no way to settle it.
        payment = member_payment_queryset(request.user, makerspace_id).filter(
            pk=payment_id,
            status=Payment.Status.PENDING,
        ).first()
        if payment is None:
            raise NotFound()
        try:
            payload = create_mobile_intent(payment.pk, actor=request.user)
        except Payment.DoesNotExist as exc:
            raise NotFound() from exc
        except PaymentRailConflict:
            return Response(
                {
                    'detail': 'The payment already uses a different online payment rail.',
                    'code': 'payment_rail_conflict',
                },
                status=status.HTTP_409_CONFLICT,
            )
        except stripe_client.PaymentsUnavailable:
            return Response(
                {
                    'detail': 'Payments are temporarily unavailable.',
                    'code': 'payments_unavailable',
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            # Provider/network failures must not escape into an owning workflow
            # or reveal Stripe diagnostics to the native client.
            return Response(
                {
                    'detail': 'Payments are temporarily unavailable.',
                    'code': 'payments_unavailable',
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(payload)
