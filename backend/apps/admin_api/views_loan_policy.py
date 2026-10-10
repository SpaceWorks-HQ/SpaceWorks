from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_loan_policy import ReturnPolicySerializer
from apps.audit import services as audit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module, require_module_locked
from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy
from apps.makerspaces.servability import servable_queryset

ERRORS = {400: ErrorSerializer, 401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer}


class ReturnPolicyView(APIView):
    permission_classes = [IsActiveStaff]

    def _makerspace(self, request, makerspace_id):
        makerspace = get_object_or_404(rbac.scope_by_action(
            request.user, rbac.Action.MANAGE_MAKERSPACE, servable_queryset(), field="pk",
        ), pk=makerspace_id)
        return require_module(makerspace, "request_workflow")

    @extend_schema(tags=["Admin makerspaces"], request=None,
                   responses={200: ReturnPolicySerializer, **ERRORS})
    def get(self, request, makerspace_id):
        makerspace = self._makerspace(request, makerspace_id)
        return Response(ReturnPolicySerializer(MakerspaceLoanPolicy.for_makerspace(makerspace)).data)

    @extend_schema(tags=["Admin makerspaces"], request=ReturnPolicySerializer,
                   responses={200: ReturnPolicySerializer, **ERRORS})
    def patch(self, request, makerspace_id):
        makerspace = self._makerspace(request, makerspace_id)
        with transaction.atomic():
            makerspace = require_module_locked(makerspace, "request_workflow")
            policy = MakerspaceLoanPolicy.for_makerspace(makerspace)
            before = {key: value for key, value in ReturnPolicySerializer(policy).data.items() if key != "id"}
            serializer = ReturnPolicySerializer(policy, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            policy = serializer.save()
            # Keep old API clients/settings coherent with the policy's default period.
            makerspace.default_loan_days = policy.default_loan_days
            makerspace.save(update_fields=["default_loan_days"])
            audit.record(request.user, "makerspace.return_policy_updated", makerspace=makerspace,
                         target=policy, meta={"before": before, "after": {
                             key: value for key, value in serializer.data.items() if key != "id"
                         }})
        return Response(serializer.data)
