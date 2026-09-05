from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.accounts import rbac
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.payments.models import Payment
from apps.payments.reconciliation import list_payments, reconcile_payments
from apps.payments.serializers_reconciliation import (
    PaymentBulkActionSerializer,
    PaymentBulkOfflineSerializer,
    PaymentListFilterSerializer,
    PaymentOfflineSerializer,
    PaymentReconciliationSerializer,
)
from apps.makerspaces.servability import servable_queryset
from apps.payments.subjects import resolve_subject_labels

ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid payment request."),
    403: OpenApiResponse(ErrorSerializer, description="Permission denied."),
    404: OpenApiResponse(ErrorSerializer, description="Payment or makerspace not found."),
    409: OpenApiResponse(ErrorSerializer, description="Payment is already terminal."),
}


class PaymentListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Payments"],
        summary="List makerspace payments for reconciliation",
        request=None,
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, enum=Payment.Status.values),
            OpenApiParameter("subject_type", OpenApiTypes.STR, enum=Payment.SubjectType.values),
        ],
        responses={200: PaymentReconciliationSerializer(many=True), **ERRORS},
    )
    def get(self, request, makerspace_id):
        get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )
        filters = PaymentListFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        rows = list(
            list_payments(
                actor=request.user,
                makerspace_id=makerspace_id,
                **filters.validated_data,
            )
        )
        context = {"payment_subject_labels": resolve_subject_labels(rows)}
        return Response(
            PaymentReconciliationSerializer(rows, many=True, context=context).data
        )


class _PaymentActionView(APIView):
    permission_classes = [IsActiveStaff]
    target_status = None
    #: Offline settlement carries a receipt; waiving does not, since no money moved.
    settlement_serializer = None

    def post(self, request, makerspace_id, payment_id):
        settlement = None
        if self.settlement_serializer is not None:
            payload = self.settlement_serializer(data=request.data)
            payload.is_valid(raise_exception=True)
            settlement = payload.validated_data["settlement"]
        payment = reconcile_payments(
            actor=request.user,
            makerspace_id=makerspace_id,
            payment_ids=[payment_id],
            target_status=self.target_status,
            settlement=settlement,
        )[0]
        context = {
            "payment_subject_labels": resolve_subject_labels([payment])
        }
        return Response(PaymentReconciliationSerializer(payment, context=context).data)


class PaymentMarkOfflineView(_PaymentActionView):
    target_status = Payment.Status.PAID_OFFLINE
    settlement_serializer = PaymentOfflineSerializer

    @extend_schema(
        tags=["Payments"], summary="Mark a payment paid offline",
        request=PaymentOfflineSerializer,
        responses={200: PaymentReconciliationSerializer, **ERRORS},
    )
    def post(self, request, makerspace_id, payment_id):
        return super().post(request, makerspace_id, payment_id)


class PaymentWaiveView(_PaymentActionView):
    target_status = Payment.Status.WAIVED

    @extend_schema(
        tags=["Payments"], summary="Waive a payment", request=None,
        responses={200: PaymentReconciliationSerializer, **ERRORS},
    )
    def post(self, request, makerspace_id, payment_id):
        return super().post(request, makerspace_id, payment_id)


class _PaymentBulkActionView(APIView):
    permission_classes = [IsActiveStaff]
    target_status = None
    request_serializer = PaymentBulkActionSerializer

    def post(self, request, makerspace_id):
        payload = self.request_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        # One receipt covers the batch: staff settling several charges in one handover
        # took the money once, and splitting it into per-row receipts would invent detail
        # nobody entered.
        payments = reconcile_payments(
            actor=request.user,
            makerspace_id=makerspace_id,
            payment_ids=payload.validated_data["ids"],
            target_status=self.target_status,
            settlement=payload.validated_data.get("settlement"),
        )
        context = {
            "payment_subject_labels": resolve_subject_labels(payments)
        }
        return Response(
            PaymentReconciliationSerializer(payments, many=True, context=context).data
        )


class PaymentBulkMarkOfflineView(_PaymentBulkActionView):
    target_status = Payment.Status.PAID_OFFLINE
    request_serializer = PaymentBulkOfflineSerializer

    @extend_schema(
        tags=["Payments"], summary="Mark payments paid offline in one transaction",
        request=PaymentBulkOfflineSerializer,
        responses={200: PaymentReconciliationSerializer(many=True), **ERRORS},
    )
    def post(self, request, makerspace_id):
        return super().post(request, makerspace_id)


class PaymentBulkWaiveView(_PaymentBulkActionView):
    target_status = Payment.Status.WAIVED

    @extend_schema(
        tags=["Payments"], summary="Waive payments in one transaction",
        request=PaymentBulkActionSerializer,
        responses={200: PaymentReconciliationSerializer(many=True), **ERRORS},
    )
    def post(self, request, makerspace_id):
        return super().post(request, makerspace_id)
