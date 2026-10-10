from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.machines import role_scope
from apps.machines.models import MachineServiceRequest
from apps.payments.models import Payment
from apps.payments.reconciliation import reconcile_payments
from apps.payments.serializers import StaffPaymentSerializer
from apps.payments.serializers_reconciliation import PaymentOfflineSerializer
from apps.payments.services import mark_offline, waive  # noqa: F401


def _manageable_payment(actor, pk):
    payment = get_object_or_404(rbac.scope_by_action(actor, rbac.Action.MANAGE_MACHINES, Payment.objects.select_related("makerspace"), field="makerspace_id"), pk=pk)
    if payment.subject_type != Payment.SubjectType.MACHINE_SERVICE_REQUEST:
        raise PermissionDenied()
    # A charge carries what the job cost and who owed it, so it follows the same machine
    # scope as the job. 404 rather than 403: an out-of-scope job is not the actor's to
    # know exists, and the detail-lookup convention in this codebase is to hide it.
    subject = MachineServiceRequest.objects.filter(pk=payment.subject_id).first()
    if subject is None or not role_scope.covers_service_request(actor, subject):
        raise Http404()
    return payment


class _PaymentActionView(APIView):
    permission_classes = [IsActiveStaff]
    operation = None

    def post(self, request, pk):
        payment = _manageable_payment(request.user, pk)
        if self.operation == "offline":
            # Same receipt contract as the generic reconciliation routes: a charge marked
            # paid offline must always be able to say how and when the money arrived.
            payload = PaymentOfflineSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            payment = reconcile_payments(
                actor=request.user,
                makerspace_id=payment.makerspace_id,
                payment_ids=[payment.pk],
                target_status=Payment.Status.PAID_OFFLINE,
                settlement=payload.validated_data["settlement"],
            )[0]
        else:
            # Through the batch service, not the `waive` convenience: that one returns a
            # terminal row unchanged with a 200, so this route reported success for a
            # charge that had already been settled while the generic waive route said 409.
            payment = reconcile_payments(
                actor=request.user,
                makerspace_id=payment.makerspace_id,
                payment_ids=[payment.pk],
                target_status=Payment.Status.WAIVED,
            )[0]
        return Response(StaffPaymentSerializer(payment).data)


_ERRORS = {
    401: OpenApiResponse(ErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(ErrorSerializer, description="Permission denied."),
    404: OpenApiResponse(ErrorSerializer, description="Payment not found or out of machine scope."),
    409: OpenApiResponse(ErrorSerializer, description="`payment_terminal`: already reconciled."),
}


class PaymentMarkOfflineView(_PaymentActionView):
    operation = "offline"

    @extend_schema(
        tags=["Payments"], summary="Mark a machine-service payment paid offline",
        request=PaymentOfflineSerializer,
        responses={
            200: StaffPaymentSerializer,
            400: OpenApiResponse(ErrorSerializer, description="Missing or invalid settlement receipt."),
            **_ERRORS,
        },
    )
    def post(self, request, pk):
        return super().post(request, pk)


class PaymentWaiveView(_PaymentActionView):
    operation = "waive"

    @extend_schema(
        tags=["Payments"], summary="Waive a machine-service payment", request=None,
        responses={200: StaffPaymentSerializer, **_ERRORS},
    )
    def post(self, request, pk):
        return super().post(request, pk)
