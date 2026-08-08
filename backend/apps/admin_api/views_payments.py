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
from apps.payments.serializers import StaffPaymentSerializer
from apps.payments.services import mark_offline, waive


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
        payment = mark_offline(payment, request.user) if self.operation == "offline" else waive(payment, request.user)
        return Response(StaffPaymentSerializer(payment).data)


class PaymentMarkOfflineView(_PaymentActionView):
    operation = "offline"

    @extend_schema(tags=["Payments"], summary="Mark a machine-service payment paid offline", request=None, responses={200: StaffPaymentSerializer, 403: OpenApiResponse(ErrorSerializer), 404: OpenApiResponse(ErrorSerializer)})
    def post(self, request, pk):
        return super().post(request, pk)


class PaymentWaiveView(_PaymentActionView):
    operation = "waive"

    @extend_schema(tags=["Payments"], summary="Waive a machine-service payment", request=None, responses={200: StaffPaymentSerializer, 403: OpenApiResponse(ErrorSerializer), 404: OpenApiResponse(ErrorSerializer)})
    def post(self, request, pk):
        return super().post(request, pk)
