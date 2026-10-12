from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests import workflow
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.guards import require_feature, require_module
from apps.makerspaces.models import Makerspace


class LoanRenewalSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    return_due_at = serializers.DateTimeField()
    renewal_count = serializers.IntegerField()


class EmptyRenewalSerializer(serializers.Serializer):
    pass


class MemberLoanRenewView(APIView):
    permission_classes = [IsAuthenticated]
    staff = False

    @extend_schema(tags=["Loans"], summary="Extend an issued loan within its policy",
                   request={"type": "object", "properties": {}}, responses={
                       200: LoanRenewalSerializer, 400: ErrorSerializer,
                       401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer,
                   })
    def post(self, request, makerspace_id, pk):
        payload = EmptyRenewalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        if self.staff:
            spaces = rbac.scope_by_action(request.user, rbac.Action.ACCEPT_REQUEST, Makerspace.objects.all(), field="pk")
            rows = rbac.scope_by_action(request.user, rbac.Action.ACCEPT_REQUEST, HardwareRequest.objects.all())
        else:
            spaces = rbac.scope_by_makerspace(request.user, Makerspace.objects.all(), makerspace_field="pk")
            rows = rbac.scope_by_makerspace(request.user, HardwareRequest.objects.all()).filter(requester=request.user)
        makerspace = get_object_or_404(spaces, pk=makerspace_id)
        require_module(makerspace, "request_workflow")
        if not self.staff:
            require_module(makerspace, "membership")
        require_feature(makerspace, "loans.renewals")
        loan = get_object_or_404(rows, pk=pk, makerspace=makerspace)
        updated = workflow.renew_loan(request.user, loan, staff=self.staff)
        return Response(LoanRenewalSerializer(updated).data)


class StaffLoanRenewView(MemberLoanRenewView):
    permission_classes = [IsActiveStaff]
    staff = True
