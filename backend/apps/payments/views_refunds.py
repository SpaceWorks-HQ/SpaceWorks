"""Staff refund endpoint. Gated exactly like waive: same subject-authority helper."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.payments.models import Payment
from apps.payments.reconciliation import _require_subject_authority
from apps.payments.serializers_reconciliation import (
    PaymentReconciliationSerializer,
    PaymentRefundRequestSerializer,
)
from apps.payments.services_refunds import refund_payment
from apps.payments.subjects import resolve_subject_labels


class PaymentRefundView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Payments"],
        summary="Refund a payment settled online, fully or partially",
        description=(
            "Sends money back through the provider that took it and records a Refund line "
            "on the payment. Only `paid_online` payments qualify; the sum of pending and "
            "succeeded refunds can never exceed the payment amount. The Payment row itself "
            "is immutable -- refund state lives on the Refund rows returned in `refunds`."
        ),
        request=PaymentRefundRequestSerializer,
        responses={
            200: PaymentReconciliationSerializer,
            400: OpenApiResponse(ErrorSerializer, description="Refund not allowed or over the balance."),
            403: OpenApiResponse(ErrorSerializer, description="Permission denied."),
            404: OpenApiResponse(ErrorSerializer, description="Payment or makerspace not found."),
            502: OpenApiResponse(ErrorSerializer, description="The provider rejected the refund."),
        },
    )
    def post(self, request, makerspace_id, payment_id):
        payload = PaymentRefundRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        payment = (
            Payment.objects.select_related("makerspace")
            .filter(makerspace_id=makerspace_id, pk=payment_id)
            .first()
        )
        if payment is None:
            raise NotFound("Payment not found.")
        _require_subject_authority(request.user, [payment])
        refund_payment(
            payment,
            amount=payload.validated_data["amount"],
            reason=payload.validated_data.get("reason", ""),
            actor=request.user,
        )
        payment = Payment.objects.prefetch_related("refunds").get(pk=payment.pk)
        context = {"payment_subject_labels": resolve_subject_labels([payment])}
        return Response(PaymentReconciliationSerializer(payment, context=context).data)
