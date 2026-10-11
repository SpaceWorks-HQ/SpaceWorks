from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.exceptions import ValidationError
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, IsActiveSuperAdmin, require_action
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.operations import services
from apps.operations.models import StocktakeSession
from apps.operations.serializers import (
    EmptySerializer,
    GenericObjectSerializer,
    StocktakeCreateSerializer,
    StocktakeLineInputSerializer,
    StocktakeLineSerializer,
    StocktakeScanInputSerializer,
    StocktakeScanResultSerializer,
    StocktakeSerializer,
)


STOCKTAKE_ERROR_RESPONSES = {
    400: OpenApiResponse(GenericObjectSerializer, description="Invalid request or stocktake state."),
    401: OpenApiResponse(description="Authentication credentials were not provided."),
    403: OpenApiResponse(description="Permission denied."),
    404: OpenApiResponse(description="Not found."),
}


@extend_schema_view(
    get=extend_schema(tags=["Stocktake"], summary="List stocktakes", request=None, parameters=[OpenApiParameter("status", str, enum=list(StocktakeSession.Status.values))], responses={200: StocktakeSerializer(many=True), **STOCKTAKE_ERROR_RESPONSES}),
    post=extend_schema(tags=["Stocktake"], summary="Create stocktake", request=StocktakeCreateSerializer, responses={201: StocktakeSerializer, **STOCKTAKE_ERROR_RESPONSES}),
)
class StocktakeListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsActiveStaff]

    def get_serializer_class(self):
        return StocktakeCreateSerializer if self.request.method == "POST" else StocktakeSerializer

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "stocktake")
        require_action(self.request.user, rbac.Action.VIEW_INVENTORY, makerspace_id)
        queryset = rbac.scope_by_action(self.request.user, rbac.Action.VIEW_INVENTORY, StocktakeSession.objects.all()).filter(makerspace_id=makerspace_id)
        status_value = self.request.query_params.get("status", "")
        if status_value:
            if status_value not in StocktakeSession.Status.values:
                raise ValidationError({"status": "Unknown stocktake status."})
            queryset = queryset.filter(status=status_value)
        return queryset.prefetch_related("lines").order_by("-started_at")

    def create(self, request, *args, **kwargs):
        makerspace = get_object_or_404(
            rbac.scope_by_visibility_or_action(
                request.user, rbac.Action.EDIT_INVENTORY, Makerspace.objects.all(), field="id",
            ), pk=self.kwargs["makerspace_id"],
        )
        require_module(makerspace, "stocktake")
        require_action(request.user, rbac.Action.EDIT_INVENTORY, makerspace.id)
        serializer = StocktakeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stocktake = services.create_stocktake(request.user, makerspace, serializer.validated_data)
        return Response(StocktakeSerializer(stocktake).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=["Stocktake"], summary="Retrieve stocktake", request=None, responses={200: StocktakeSerializer, **STOCKTAKE_ERROR_RESPONSES}),
)
class StocktakeDetailView(generics.RetrieveAPIView):
    serializer_class = StocktakeSerializer
    permission_classes = [IsActiveStaff]

    def get_queryset(self):
        return rbac.scope_by_action(self.request.user, rbac.Action.VIEW_INVENTORY, StocktakeSession.objects.prefetch_related("lines"))


class StocktakeCountLineView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = StocktakeLineInputSerializer

    @extend_schema(tags=["Stocktake"], summary="Count stocktake line", request=StocktakeLineInputSerializer, responses={201: StocktakeLineSerializer, **STOCKTAKE_ERROR_RESPONSES})
    def post(self, request, pk, *args, **kwargs):
        stocktake = _stocktake_for_action(request.user, pk, rbac.Action.EDIT_INVENTORY)
        serializer = StocktakeLineInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        line = services.add_stocktake_line(request.user, stocktake, serializer.validated_data)
        return Response(StocktakeLineSerializer(line).data, status=status.HTTP_201_CREATED)


class StocktakeResolveScanView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = StocktakeScanInputSerializer

    @extend_schema(tags=["Stocktake"], summary="Resolve a scanned QR to a stocktake count target", request=StocktakeScanInputSerializer, responses={200: StocktakeScanResultSerializer, **STOCKTAKE_ERROR_RESPONSES})
    def post(self, request, pk, *args, **kwargs):
        stocktake = _stocktake_for_action(request.user, pk, rbac.Action.EDIT_INVENTORY)
        serializer = StocktakeScanInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.resolve_scan_target(request.user, stocktake, serializer.validated_data["payload"])
        return Response(result)


class StocktakeCompleteView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(tags=["Stocktake"], summary="Complete stocktake", request=EmptySerializer, responses={200: StocktakeSerializer, **STOCKTAKE_ERROR_RESPONSES})
    def post(self, request, pk, *args, **kwargs):
        stocktake = _stocktake_for_action(request.user, pk, rbac.Action.EDIT_INVENTORY)
        return Response(StocktakeSerializer(services.complete_stocktake(request.user, stocktake)).data)


class StocktakeApproveView(APIView):
    permission_classes = [IsActiveSuperAdmin]
    serializer_class = EmptySerializer

    @extend_schema(tags=["Stocktake"], summary="Approve stocktake", request=EmptySerializer, responses={200: StocktakeSerializer, **STOCKTAKE_ERROR_RESPONSES})
    def post(self, request, pk, *args, **kwargs):
        stocktake = _stocktake_for_action(request.user, pk, rbac.Action.EDIT_INVENTORY)
        return Response(StocktakeSerializer(services.approve_stocktake(request.user, stocktake)).data)


class StocktakeApplyAdjustmentsView(APIView):
    permission_classes = [IsActiveSuperAdmin]
    serializer_class = EmptySerializer

    @extend_schema(tags=["Stocktake"], summary="Apply stocktake adjustments", request=EmptySerializer, responses={200: StocktakeSerializer, **STOCKTAKE_ERROR_RESPONSES})
    def post(self, request, pk, *args, **kwargs):
        stocktake = _stocktake_for_action(request.user, pk, rbac.Action.EDIT_INVENTORY)
        return Response(StocktakeSerializer(services.apply_stocktake_adjustments(request.user, stocktake)).data)


def _stocktake_for_action(user, pk, action):
    stocktake = get_object_or_404(rbac.scope_by_action(user, action, StocktakeSession.objects.all()), pk=pk)
    require_module(stocktake.makerspace, "stocktake")
    return stocktake
