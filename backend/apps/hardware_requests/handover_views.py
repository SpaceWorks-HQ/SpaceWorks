from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.hardware_requests import workflow
from apps.hardware_requests.permissions import (
    CanAssignBox,
    CanIssueRequest,
    CanReviewRequest,
    CanReturnRequest,
)
from apps.hardware_requests.serializers import (
    AdminRequestSerializer,
    AssignBoxSerializer,
    IssueRequestSerializer,
    ReturnDueSerializer,
    ReturnRequestSerializer,
)
from apps.hardware_requests.view_helpers import (
    ACTION_ERROR_RESPONSES,
    ERROR_503,
    handover_surface_module,
    request_queryset,
)
from apps.makerspaces.guards import require_module


class AssignBoxView(APIView):
    permission_classes = [CanAssignBox]

    @extend_schema(
        tags=["Admin requests"],
        summary="Assign box to accepted request",
        request=AssignBoxSerializer,
        responses={200: AdminRequestSerializer, **ACTION_ERROR_RESPONSES},
    )
    def post(self, request, pk, *args, **kwargs):
        hardware_request = _scoped_action_request(
            request,
            pk,
            rbac.Action.ASSIGN_BOX,
        )
        serializer = AssignBoxSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = workflow.assign_box(
            request.user,
            hardware_request,
            serializer.validated_data["box_code"],
        )
        return Response(AdminRequestSerializer(updated).data)


class IssueRequestView(APIView):
    permission_classes = [CanIssueRequest]

    @extend_schema(
        tags=["Admin requests"],
        summary="Issue accepted request",
        request=IssueRequestSerializer,
        responses={200: AdminRequestSerializer, **ACTION_ERROR_RESPONSES, 503: ERROR_503},
    )
    def post(self, request, pk, *args, **kwargs):
        hardware_request = _scoped_action_request(
            request,
            pk,
            rbac.Action.ISSUE_REQUEST,
        )
        serializer = IssueRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = workflow.issue_request(
            request.user,
            hardware_request,
            serializer.validated_data["evidence_id"],
            serializer.validated_data["remark"],
            asset_qr_payloads=serializer.validated_data["asset_qr_payloads"],
            rejects=serializer.validated_data["rejects"],
        )
        return Response(AdminRequestSerializer(updated).data)


class ReturnRequestView(APIView):
    permission_classes = [CanReturnRequest]

    @extend_schema(
        tags=["Admin requests"],
        summary="Return issued request items",
        request=ReturnRequestSerializer,
        responses={200: AdminRequestSerializer, **ACTION_ERROR_RESPONSES, 503: ERROR_503},
    )
    def post(self, request, pk, *args, **kwargs):
        hardware_request = _scoped_action_request(
            request,
            pk,
            rbac.Action.RETURN_REQUEST,
        )
        serializer = ReturnRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = workflow.return_items(
            request.user,
            hardware_request,
            serializer.validated_data["evidence_id"],
            serializer.validated_data["remark"],
            serializer.validated_data["box_code"],
            serializer.validated_data["resolutions"],
        )
        return Response(AdminRequestSerializer(updated).data)


class SetReturnDueView(APIView):
    permission_classes = [CanReviewRequest]

    @extend_schema(
        tags=["Admin requests"],
        summary="Set request return due time",
        request=ReturnDueSerializer,
        responses={200: AdminRequestSerializer, **ACTION_ERROR_RESPONSES},
    )
    def post(self, request, pk, *args, **kwargs):
        hardware_request = _scoped_action_request(
            request,
            pk,
            rbac.Action.ACCEPT_REQUEST,
        )
        serializer = ReturnDueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = workflow.set_return_due(
            request.user,
            hardware_request,
            serializer.validated_data["return_due_at"],
        )
        return Response(AdminRequestSerializer(updated).data)


def _scoped_action_request(request, pk, action):
    """Scope by RBAC action, then gate on the module that owns THIS URL surface.

    The action is the authority; the module is only the surface. Keying the module on the
    action instead made `guest_handover` -- an optional module -- refuse `assign_box`,
    `issue` and `return` for every actor including a full Space Manager, so a core-only
    install could accept a request and then never fulfil it.
    """
    scoped = rbac.scope_by_action(request.user, action, request_queryset())
    hardware_request = get_object_or_404(scoped, pk=pk)
    require_module(hardware_request.makerspace, handover_surface_module(request))
    return hardware_request
