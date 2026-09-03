from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.evidence.retention_policy import (
    policy_payload,
    preview_object_expiry,
    update_policy,
)
from apps.evidence.serializers import (
    EvidenceRetentionPatchSerializer,
    EvidenceRetentionPolicySerializer,
    EvidenceRetentionPreviewRequestSerializer,
    EvidenceRetentionPreviewResponseSerializer,
)
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace


AUTH_ERRORS = {
    401: OpenApiResponse(description="Authentication is required."),
    403: OpenApiResponse(description="Active manage-events permission is required."),
    404: OpenApiResponse(description="Makerspace was not found in the actor's scope."),
    503: OpenApiResponse(description="Deployment recovery is active."),
}


def _manageable_makerspace(actor, makerspace_id):
    queryset = rbac.scope_by_visibility_or_action(
        actor,
        rbac.Action.MANAGE_EVENTS,
        Makerspace.objects.all(),
        field="id",
    )
    queryset = rbac.hide_from_superadmin(actor, queryset, field="id")
    makerspace = get_object_or_404(queryset, pk=makerspace_id)
    require_module(makerspace, "evidence_uploads")
    if not rbac.can(actor, rbac.Action.MANAGE_EVENTS, makerspace.pk):
        raise PermissionDenied()
    return makerspace


class EvidenceRetentionPolicyView(APIView):
    permission_classes = [IsAuthenticated, IsActiveStaff]

    @extend_schema(
        tags=["Evidence retention"],
        summary="Get a makerspace evidence object-retention policy",
        responses={200: EvidenceRetentionPolicySerializer, **AUTH_ERRORS},
    )
    def get(self, request, makerspace_id):
        makerspace = _manageable_makerspace(request.user, makerspace_id)
        return Response(EvidenceRetentionPolicySerializer(policy_payload(makerspace)).data)

    @extend_schema(
        tags=["Evidence retention"],
        summary="Set or clear a makerspace evidence object-retention override",
        request=EvidenceRetentionPatchSerializer,
        responses={
            200: EvidenceRetentionPolicySerializer,
            400: OpenApiResponse(description="Retention days are invalid."),
            **AUTH_ERRORS,
        },
    )
    def patch(self, request, makerspace_id):
        makerspace = _manageable_makerspace(request.user, makerspace_id)
        serializer = EvidenceRetentionPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = update_policy(
            makerspace,
            request.user,
            serializer.validated_data["object_retention_days"],
        )
        return Response(EvidenceRetentionPolicySerializer(payload).data)


class EvidenceRetentionPreviewView(APIView):
    permission_classes = [IsAuthenticated, IsActiveStaff]

    @extend_schema(
        tags=["Evidence retention"],
        summary="Preview evidence objects eligible for expiry",
        request=EvidenceRetentionPreviewRequestSerializer,
        responses={
            200: EvidenceRetentionPreviewResponseSerializer,
            400: OpenApiResponse(description="Preview limit is invalid."),
            **AUTH_ERRORS,
        },
    )
    def post(self, request, makerspace_id):
        makerspace = _manageable_makerspace(request.user, makerspace_id)
        serializer = EvidenceRetentionPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = preview_object_expiry(
            makerspace,
            limit=serializer.validated_data["limit"],
        )
        return Response(EvidenceRetentionPreviewResponseSerializer(payload).data)
