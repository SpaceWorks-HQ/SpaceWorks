"""Core-ledger staff endpoint: works without the online payments rail."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.payments.reconciliation import with_refunds
from apps.payments.serializers_reconciliation import PaymentReconciliationSerializer
from apps.payments.serializers_refunds_offline import PaymentOfflineRefundSerializer, PaymentRefundAmendSerializer
from apps.payments.services_refunds_offline import offline_refund_queryset, record_offline_refund, amend_offline_refund
from apps.payments.subjects import resolve_subject_labels
from apps.payments.schemas_billing import MANUAL_REFUND_ERROR


class PaymentOfflineRefundView(APIView):
    permission_classes = [IsActiveStaff]
    release_deposit = False

    @extend_schema(
        tags=["Payments"], summary="Record an offline refund or release a cash loan deposit",
        description=(
            "Requires active staff and record_payment. "
            "Records money already returned on a paid_offline charge, fully or partially, "
            "with method, optional financial reference and refunded_at. The receipt is "
            "append-only and audited; all pending/succeeded refunds share one balance. "
            "No provider call or payments module is required. The Payment remains unchanged."
        ),
        request=PaymentOfflineRefundSerializer,
        responses={
            200: PaymentReconciliationSerializer,
            400: OpenApiResponse(MANUAL_REFUND_ERROR, description="Invalid receipt, status or refund balance."),
            401: OpenApiResponse(ErrorSerializer, description="Authentication required."),
            403: OpenApiResponse(ErrorSerializer, description="Record payment and active status required."),
            404: OpenApiResponse(ErrorSerializer, description="Payment not found in the permitted makerspace."),
        },
    )
    def post(self, request, makerspace_id, payment_id):
        payload = PaymentOfflineRefundSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        # Scope before retrieval; guessing a foreign payment id cannot disclose it.
        allowed = offline_refund_queryset(request.user)
        payment = allowed.select_related("makerspace").filter(pk=payment_id, makerspace_id=makerspace_id).first()
        if payment is None:
            raise NotFound("Payment not found.")
        record_offline_refund(payment, actor=request.user, release_deposit=self.release_deposit, **payload.validated_data)
        payment = with_refunds(allowed).get(pk=payment.pk)
        return Response(PaymentReconciliationSerializer(payment, context={
            "payment_subject_labels": resolve_subject_labels([payment]),
        }).data)


class PaymentDepositReleaseView(PaymentOfflineRefundView):
    release_deposit = True

    @extend_schema(
        tags=["Payments"], summary="Record a deposit returned after a loan closes",
        description="Requires record_payment. Only a paid_offline loan deposit on a returned or closed_with_issue loan is eligible. Records actual money returned; never offsets fees or calls the rail.",
        request=PaymentOfflineRefundSerializer,
        responses={200: PaymentReconciliationSerializer, **{
            code: OpenApiResponse(ErrorSerializer) for code in (400, 401, 403, 404)
        }, 400: OpenApiResponse(MANUAL_REFUND_ERROR)},
    )
    def post(self, request, makerspace_id, payment_id):
        return super().post(request, makerspace_id, payment_id)


class PaymentRefundAmendView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Payments"], summary="Append a corrected manual refund receipt",
        description="Requires record_payment. Replaces method, reference and returned date on the effective receipt; amount/currency and the original payment never change. No second refund event or transfer occurs.",
        request=PaymentRefundAmendSerializer,
        responses={200: PaymentReconciliationSerializer, **{
            code: OpenApiResponse(ErrorSerializer) for code in (400, 401, 403, 404)
        }, 400: OpenApiResponse(MANUAL_REFUND_ERROR)},
    )
    def post(self, request, makerspace_id, payment_id, refund_id):
        payload = PaymentRefundAmendSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        allowed = offline_refund_queryset(request.user)
        payment = allowed.filter(pk=payment_id, makerspace_id=makerspace_id).first()
        if payment is None:
            raise NotFound("Payment not found.")
        amend_offline_refund(payment, refund_id=refund_id, actor=request.user, **payload.validated_data)
        payment = with_refunds(allowed).get(pk=payment.pk)
        return Response(PaymentReconciliationSerializer(payment, context={
            "payment_subject_labels": resolve_subject_labels([payment]),
        }).data)
