from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.boxes.access import locked_qr_for_action, makerspace_for_action, qr_for_action
from apps.boxes.api_views_eligibility import _allowed_scanner_actions
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.boxes.qr_render import render_qr_label_svg
from apps.boxes.serializers import (
    BoxSerializer,
    CreateBoxQrSerializer,
    CreateToolQrSerializer,
    QrCodeSerializer,
    QrRebindResultSerializer,
    QrRebindTargetSerializer,
    QrResolveResultSerializer,
    QrResolveSerializer,
    QrScanResultSerializer,
    QrScanSerializer,
    qr_target_payload,
)
from apps.boxes.rebind import rebind_qr_target
from apps.boxes.services import revoke_qr_code
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.guards import require_module
from apps.openapi import (
    QR_BOX_EXAMPLE,
    QR_RESOLVE_REQUEST_EXAMPLE,
    QR_RESOLVE_RESPONSE_EXAMPLE,
    QR_SCAN_EXAMPLE,
)


class QrPermissionMixin:
    permission_classes = [IsActiveStaff]

    def _require_qr(self, user, makerspace_id):
        require_module(makerspace_id, "qr_management")
        if (
            user.access_status != User.AccessStatus.ACTIVE
            or not rbac.can(user, rbac.Action.MANAGE_QR, makerspace_id)
        ):
            raise PermissionDenied()


class CreateBoxQrView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Create a QR-coded box",
        request=CreateBoxQrSerializer,
        responses={201: BoxSerializer},
        examples=[QR_BOX_EXAMPLE],
    )
    def post(self, request, *args, **kwargs):
        serializer = CreateBoxQrSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        makerspace = makerspace_for_action(request.user, rbac.Action.MANAGE_QR, data["makerspace_id"])
        self._require_qr(request.user, makerspace.id)
        parent = None
        if data.get("parent_id"):
            parent = get_object_or_404(Box, pk=data["parent_id"], makerspace=makerspace)
        box = Box.objects.create(
            makerspace=makerspace,
            parent=parent,
            label=data["label"],
            location=data.get("location", ""),
            description=data.get("description", ""),
        )
        QrCode.objects.create(
            makerspace=makerspace,
            payload=box.code,
            target_type=QrCode.TargetType.BOX,
            target_id=box.id,
            created_by=request.user,
        )
        audit.record(request.user, "qr.box_created", makerspace=makerspace, target=box)
        return Response(BoxSerializer(box).data, status=status.HTTP_201_CREATED)


class CreateToolQrView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Create or reuse a QR code for a product or asset",
        request=CreateToolQrSerializer,
        responses={201: QrCodeSerializer},
    )
    def post(self, request, *args, **kwargs):
        serializer = CreateToolQrSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        makerspace = makerspace_for_action(request.user, rbac.Action.MANAGE_QR, data["makerspace_id"])
        self._require_qr(request.user, makerspace.id)
        if data.get("asset_id"):
            target = get_object_or_404(InventoryAsset, pk=data["asset_id"], makerspace=makerspace)
            target_type = QrCode.TargetType.ASSET
        else:
            target = get_object_or_404(InventoryProduct, pk=data["product_id"], makerspace=makerspace)
            if target.tracking_mode == TrackingMode.INDIVIDUAL:
                raise ValidationError("Individual-tracked inventory requires unit QR codes.")
            target_type = QrCode.TargetType.PRODUCT
        qr, created = QrCode.objects.get_or_create(
            makerspace=makerspace,
            target_type=target_type,
            target_id=target.id,
            status=QrCode.Status.ACTIVE,
            defaults={"created_by": request.user},
        )
        audit.record(
            request.user,
            "qr.tool_created" if created else "qr.tool_reused",
            makerspace=makerspace,
            target=target,
            meta={"qr_id": qr.id},
        )
        return Response(QrCodeSerializer(qr).data, status=status.HTTP_201_CREATED)


class QrScanView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Record a QR scan",
        description="Context is limited to issue or return and scan events are immutable.",
        request=QrScanSerializer,
        responses={201: QrScanResultSerializer},
        examples=[QR_SCAN_EXAMPLE],
    )
    def post(self, request, *args, **kwargs):
        serializer = QrScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        qr = qr_for_action(request.user, rbac.Action.MANAGE_QR, payload=data["payload"], status=QrCode.Status.ACTIVE)
        self._require_qr(request.user, qr.makerspace_id)
        request_id = data.get("request_id")
        if request_id is not None:
            from apps.hardware_requests.models import HardwareRequest

            # The immutable scan inherits the QR's makerspace; a cross-tenant
            # request_id would silently mis-attribute it. Bind them.
            if not HardwareRequest.objects.filter(
                pk=request_id, makerspace_id=qr.makerspace_id
            ).exists():
                raise ValidationError({"request_id": "Request belongs to a different makerspace."})
        scan = QrScanEvent.objects.create(
            makerspace=qr.makerspace,
            qr_code=qr,
            actor=request.user,
            context=data["context"],
            request_id=request_id,
        )
        audit.record(
            request.user,
            "qr.scanned",
            makerspace=qr.makerspace,
            target=qr,
            meta={"context": scan.context, "scan_id": scan.id},
        )
        return Response(
            {
                "qr": QrCodeSerializer(qr).data,
                "target": qr_target_payload(qr),
                "scan_id": scan.id,
            },
            status=status.HTTP_201_CREATED,
        )


class QrResolveView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Resolve QR target and scanner allowed actions",
        description=(
            "Resolve the opaque payload encoded in a physical QR label to its target "
            "(box, product, or asset) and the scanner actions the caller may take. "
            "`payload` is the raw 32-char lowercase hex token printed on the label "
            "(Python `uuid4().hex`, e.g. `3f9a1c2b4d5e6f7081920a1b2c3d4e5f`) - it is the "
            "value stored as `QrCode.payload` (and `Box.code` for boxes), not a URL or JSON. "
            "Resolving a QR also records an immutable scanner-lookup scan event."
        ),
        request=QrResolveSerializer,
        responses={200: QrResolveResultSerializer},
        examples=[QR_RESOLVE_REQUEST_EXAMPLE, QR_RESOLVE_RESPONSE_EXAMPLE],
    )
    def post(self, request, *args, **kwargs):
        serializer = QrResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        qr = qr_for_action(request.user, rbac.Action.VIEW_INVENTORY, payload=serializer.validated_data["payload"], status=QrCode.Status.ACTIVE)
        require_module(qr.makerspace, "scanner")
        QrScanEvent.objects.create(
            makerspace=qr.makerspace,
            qr_code=qr,
            actor=request.user,
            context=QrScanEvent.Context.SCANNER_LOOKUP,
        )
        return Response(
            {
                "qr": QrCodeSerializer(qr).data,
                "target": qr_target_payload(qr),
                "allowed_actions": _allowed_scanner_actions(request.user, qr),
            }
        )


class QrPrintView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Render QR label SVG",
        responses={200: OpenApiResponse(description="SVG QR label.")},
    )
    def get(self, request, pk, *args, **kwargs):
        qr = qr_for_action(request.user, rbac.Action.MANAGE_QR, pk=pk)
        self._require_qr(request.user, qr.makerspace_id)
        return Response(
            {
                "payload": qr.payload,
                "svg": render_qr_label_svg(qr.payload),
                "target": qr_target_payload(qr),
            }
        )


class QrRevokeView(QrPermissionMixin, APIView):
    @extend_schema(
        tags=["QR assets"],
        summary="Revoke active QR code",
        request=None,
        responses={200: QrCodeSerializer},
    )
    def post(self, request, pk, *args, **kwargs):
        qr = locked_qr_for_action(request.user, rbac.Action.MANAGE_QR, pk=pk)
        self._require_qr(request.user, qr.makerspace_id)
        revoke_qr_code(request.user, qr)
        return Response(QrCodeSerializer(qr).data)


class QrRebindTargetView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["QR assets"],
        summary=(
            "Rebind a saved QR to another product/asset "
            "(cross-makerspace = superadmin) and optionally rename"
        ),
        request=QrRebindTargetSerializer,
        responses={
            200: QrRebindResultSerializer,
            409: OpenApiResponse(description="Outstanding loan or target QR conflict."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        serializer = QrRebindTargetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from django.db import transaction

        with transaction.atomic():
            result = rebind_qr_target(request.user, pk, serializer.validated_data)
        return Response(
            {
                "qr": QrCodeSerializer(result.qr).data,
                "target": qr_target_payload(result.qr),
            }
        )
