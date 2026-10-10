"""Authenticated, current-action-scoped staff recovery surface."""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.replay_recovery_policy import visible_replays
from apps.hardware_requests.replay_recovery_serializers import (
    ReplayRecoveryFilterSerializer, ReplayRecoverySerializer, ReplayResolutionSerializer,
)
from apps.hardware_requests.replay_recovery_service import failed_replay, resolve_replay
from apps.makerspaces.station_views_public import no_store

ERRORS = {code: OpenApiResponse(ErrorSerializer, description=detail) for code, detail in (
    (400, "Invalid filter/resolution or disabled required module."),
    (401, "Authentication required."), (403, "Account, current action or origin refused."),
    (404, "Failure is unavailable in your scope."), (409, "Resolution/replacement conflict."),
    (423, "Tenant source gate closed."),
)}
TAGS = ["Admin kiosk recovery"]


class ReplayRecoveryListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsActiveStaff]
    serializer_class = ReplayRecoverySerializer

    def get_queryset(self):
        filters = ReplayRecoveryFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        rows = visible_replays(self.request.user).filter(
            makerspace_id=self.kwargs["makerspace_id"], state="failed",
        ).select_related("station", "actor", "resolved_by", "predecessor")
        resolution = filters.validated_data["resolution"]
        if resolution != "all":
            rows = rows.filter(resolution_code__isnull=resolution == "unresolved")
        return rows.order_by("-completed_at", "-pk")

    @extend_schema(tags=TAGS, summary="List failed handovers visible under current per-operation actions",
                   description="Historical review remains available with inventory.kiosk disabled. No channel credentials or command payload are returned.",
                   parameters=[OpenApiParameter("state", str, enum=["failed"]),
                               OpenApiParameter("resolution", str, enum=["unresolved", "resolved", "all"])],
                   responses={200: ReplayRecoverySerializer(many=True), **ERRORS})
    def get(self, request, *args, **kwargs):
        return no_store(super().get(request, *args, **kwargs))


class ReplayRecoveryDetailView(APIView):
    permission_classes = [IsAuthenticated, IsActiveStaff]

    @extend_schema(tags=TAGS, summary="Inspect one current-action-scoped failed handover",
                   responses={200: ReplayRecoverySerializer, **ERRORS})
    def get(self, request, pk):
        row = failed_replay(request.user, pk)
        return no_store(Response(ReplayRecoverySerializer(row, context={"request": request}).data))


class ReplayRecoveryResolveView(APIView):
    permission_classes = [IsAuthenticated, IsActiveStaff]

    @extend_schema(tags=TAGS, summary="Append an idempotent review of a failed handover",
                   description="Acknowledgement records no physical change. Replacement links only a fresh succeeded replay for the same known subject; this endpoint never executes handovers.",
                   request=ReplayResolutionSerializer, responses={200: ReplayRecoverySerializer, **ERRORS})
    def post(self, request, pk):
        serializer = ReplayResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = resolve_replay(request.user, pk, **serializer.validated_data)
        return no_store(Response(ReplayRecoverySerializer(row, context={"request": request}).data))
