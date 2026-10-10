from django.http import HttpResponse
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.boxes.models import QrCode
from apps.boxes.serializers import QrCodeSerializer
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.operations import qr_zip, services
from apps.operations.models import QrPrintBatch
from apps.operations.serializers import (
    AssetGenerateResultSerializer,
    AssetGenerateSerializer,
    EmptySerializer,
    QrPrintBatchCreateSerializer,
    QrPrintBatchDetailSerializer,
    QrPrintBatchItemCreateSerializer,
    QrPrintBatchItemResultSerializer,
    QrPrintBatchSerializer,
)

QR_MUTATION_ERRORS = {
    code: OpenApiResponse(response={
        "oneOf": [{"type": "object", "additionalProperties": True},
                  {"type": "array", "items": {"type": "string"}}],
    }, description=description)
    for code, description in (
        (400, "Invalid input, disabled module, or non-draft print batch."),
        (401, "Authentication required."), (403, "QR management permission required."),
        (404, "Batch or inventory target not in scope."), (423, "Tenant frozen for migration."),
    )
}


@extend_schema_view(
    get=extend_schema(tags=["QR print batches"], summary="List QR print batches", request=None, responses={200: QrPrintBatchSerializer(many=True)}),
    post=extend_schema(tags=["QR print batches"], summary="Create QR print batch", request=QrPrintBatchCreateSerializer, responses={201: QrPrintBatchSerializer}),
)
class QrPrintBatchListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsActiveStaff]

    def get_serializer_class(self):
        return QrPrintBatchCreateSerializer if self.request.method == "POST" else QrPrintBatchSerializer

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "qr_print_batches")
        require_action(self.request.user, rbac.Action.MANAGE_QR, makerspace_id)
        return QrPrintBatch.objects.filter(makerspace_id=makerspace_id).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        makerspace = get_object_or_404(Makerspace, pk=self.kwargs["makerspace_id"])
        require_module(makerspace, "qr_print_batches")
        require_action(request.user, rbac.Action.MANAGE_QR, makerspace.id)
        serializer = QrPrintBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = QrPrintBatch.objects.create(makerspace=makerspace, title=serializer.validated_data["title"], created_by=request.user)
        audit.record(request.user, "qr_print_batch.created", makerspace=makerspace, target=batch)
        return Response(QrPrintBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=["QR print batches"], summary="Retrieve QR print batch", request=None, responses={200: QrPrintBatchDetailSerializer}),
)
class QrPrintBatchDetailView(generics.RetrieveAPIView):
    serializer_class = QrPrintBatchDetailSerializer
    permission_classes = [IsActiveStaff]

    def get_queryset(self):
        return rbac.scope_by_action(self.request.user, rbac.Action.MANAGE_QR, QrPrintBatch.objects.prefetch_related("items__qr_code"))


class QrPrintBatchItemView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = QrPrintBatchItemCreateSerializer

    @extend_schema(tags=["QR print batches"], summary="Add QR code to draft print batch", request=QrPrintBatchItemCreateSerializer, responses={201: QrPrintBatchItemResultSerializer, **QR_MUTATION_ERRORS})
    @transaction.atomic
    def post(self, request, pk, *args, **kwargs):
        batch = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, QrPrintBatch.objects.all()), pk=pk)
        require_module(batch.makerspace, "qr_print_batches")
        serializer = QrPrintBatchItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        qr = get_object_or_404(QrCode, pk=serializer.validated_data["qr_code_id"], makerspace=batch.makerspace)
        if qr.target_type not in {QrCode.TargetType.PRODUCT, QrCode.TargetType.ASSET}:
            raise ValidationError("QR print batches only accept inventory item or unit QR codes.")
        item = services.add_qr_to_batch(
            batch,
            qr,
            serializer.validated_data.get("label_text", ""),
            serializer.validated_data.get("sort_order"),
        )
        audit.record(request.user, "qr_print_batch.item_saved", makerspace=batch.makerspace,
                     target=batch, meta={"item_count": batch.items.count()})
        return Response({"id": item.id}, status=status.HTTP_201_CREATED)


class QrPrintBatchDownloadView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(
        tags=["QR print batches"],
        summary="Download QR print batch as a ZIP of captioned SVGs",
        request=None,
        responses={(200, "application/zip"): OpenApiTypes.BINARY},
    )
    def get(self, request, pk, *args, **kwargs):
        batch = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, QrPrintBatch.objects.prefetch_related("items__qr_code")), pk=pk)
        require_module(batch.makerspace, "qr_print_batches")
        data = qr_zip.build_batch_zip(batch)
        response = HttpResponse(data, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="qr-batch-{batch.id}.zip"'
        return response


class AssetGenerateView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = AssetGenerateSerializer

    @extend_schema(tags=["Asset units"], summary="Generate asset units", request=AssetGenerateSerializer, responses={201: AssetGenerateResultSerializer, **QR_MUTATION_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        product = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, InventoryProduct.objects.all()), pk=pk)
        require_module(product.makerspace, "asset_units")
        serializer = AssetGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created, batch = services.generate_assets_with_qr(request.user, product, serializer.validated_data)
        return Response(
            {
                "assets": [
                    {"id": pair["asset"].id, "asset_tag": pair["asset"].asset_tag, "qr": QrCodeSerializer(pair["qr"]).data}
                    for pair in created
                ],
                "print_batch_id": batch.id if batch else None,
            },
            status=status.HTTP_201_CREATED,
        )


class AssetQrView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(tags=["Asset units"], summary="Create asset QR code", request=EmptySerializer, responses={201: QrCodeSerializer})
    def post(self, request, pk, *args, **kwargs):
        asset = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, InventoryAsset.objects.all()), pk=pk)
        require_module(asset.makerspace, "asset_units")
        qr, _ = QrCode.objects.get_or_create(
            makerspace=asset.makerspace,
            target_type=QrCode.TargetType.ASSET,
            target_id=asset.id,
            status=QrCode.Status.ACTIVE,
            defaults={"created_by": request.user},
        )
        return Response(QrCodeSerializer(qr).data, status=status.HTTP_201_CREATED)
