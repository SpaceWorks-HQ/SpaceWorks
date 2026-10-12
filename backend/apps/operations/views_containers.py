from django.db.models import OuterRef, Subquery
from django.db import transaction
from django.core.exceptions import ValidationError as ModelValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView


class ContainerPagination(PageNumberPagination):
    # Opt-in larger pages (?page_size=) so callers that need the FULL container list
    # (the direct-handout dropdown + its scan-membership check) aren't capped at page one.
    page_size_query_param = "page_size"
    max_page_size = 1000

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.boxes.serializers import BoxSerializer
from apps.makerspaces.guards import require_module, require_module_locked
from apps.makerspaces.guards import require_feature
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.operations.serializers import (
    ContainerContentsSerializer,
    ContainerHistorySerializer,
    ContainerMoveSerializer,
    GenericObjectSerializer,
)


def _with_active_box_qr(queryset):
    active_qr = QrCode.objects.filter(
        makerspace_id=OuterRef("makerspace_id"),
        target_type=QrCode.TargetType.BOX,
        target_id=OuterRef("pk"),
        status=QrCode.Status.ACTIVE,
    ).order_by("id").values("id")[:1]
    return queryset.annotate(_active_qr_code_id=Subquery(active_qr))


@extend_schema_view(
    get=extend_schema(tags=["Containers"], summary="List containers", request=None, responses={200: BoxSerializer(many=True), **{code: ErrorSerializer for code in (400, 401, 403, 404)}}),
    post=extend_schema(tags=["Containers"], summary="Create container", request=BoxSerializer, responses={201: BoxSerializer, **{code: ErrorSerializer for code in (400, 401, 403, 404)}}),
)
class ContainerListCreateView(generics.ListCreateAPIView):
    serializer_class = BoxSerializer
    permission_classes = [IsActiveStaff]
    pagination_class = ContainerPagination

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "containers")
        require_action(self.request.user, rbac.Action.VIEW_INVENTORY, makerspace_id)
        return _with_active_box_qr(rbac.scope_by_action(self.request.user, rbac.Action.VIEW_INVENTORY, Box.objects.filter(makerspace_id=makerspace_id))).order_by("label")

    @transaction.atomic
    def perform_create(self, serializer):
        makerspace_id = self.kwargs["makerspace_id"]
        space = require_module_locked(makerspace_id, "containers")
        require_action(self.request.user, rbac.Action.MANAGE_QR, makerspace_id)
        parent = serializer.validated_data.get("parent")
        if serializer.validated_data.get("kit_components"):
            require_feature(space, "loans.kit_checklist")
        if parent and parent.makerspace_id != makerspace_id:
            raise ValidationError({"parent": "Parent belongs to a different makerspace."})
        box = serializer.save(makerspace_id=makerspace_id)
        QrCode.objects.get_or_create(
            makerspace_id=makerspace_id,
            target_type=QrCode.TargetType.BOX,
            target_id=box.id,
            status=QrCode.Status.ACTIVE,
            defaults={"payload": box.code, "created_by": self.request.user},
        )
        audit.record(self.request.user, "container.created", makerspace=box.makerspace, target=box)


@extend_schema_view(
    get=extend_schema(tags=["Containers"], summary="Retrieve container", request=None, responses={200: BoxSerializer, **{code: ErrorSerializer for code in (400, 401, 403, 404)}}),
    patch=extend_schema(tags=["Containers"], summary="Update container", request=BoxSerializer, responses={200: BoxSerializer, **{code: ErrorSerializer for code in (400, 401, 403, 404)}}),
)
class ContainerDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = BoxSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        action = rbac.Action.MANAGE_QR if self.request.method == "PATCH" else rbac.Action.VIEW_INVENTORY
        return rbac.scope_by_action(self.request.user, action, Box.objects.all())

    def get_object(self):
        box = super().get_object()
        require_module(box.makerspace, "containers")
        return box

    @transaction.atomic
    def perform_update(self, serializer):
        require_module(serializer.instance.makerspace, "containers")
        parent = serializer.validated_data.get("parent")
        if parent and parent.makerspace_id != serializer.instance.makerspace_id:
            raise ValidationError({"parent": "Parent belongs to a different makerspace."})
        box = serializer.save()
        audit.record(self.request.user, "container.moved", makerspace=box.makerspace, target=box)


class ContainerMoveView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Containers"], summary="Move or update container", request=ContainerMoveSerializer, responses={200: BoxSerializer, **{code: ErrorSerializer for code in (400, 401, 403, 404)}})
    @transaction.atomic
    def post(self, request, pk, *args, **kwargs):
        scoped = rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, Box.objects.all())
        box = get_object_or_404(scoped, pk=pk)
        space = require_module_locked(box.makerspace_id, "containers")
        box = get_object_or_404(scoped.select_for_update(), pk=pk, makerspace=space)
        serializer = ContainerMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "kit_components" in data:
            require_feature(box.makerspace, "loans.kit_checklist")
        if "parent_id" in data:
            box.parent = None if data["parent_id"] is None else get_object_or_404(scoped, pk=data["parent_id"], makerspace=space)
        for field in ("label", "location", "description", "is_active", "kit_components"):
            if field in data:
                setattr(box, field, data[field])
        try:
            box.full_clean()
        except ModelValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        box.save()
        audit.record(request.user, "container.moved", makerspace=box.makerspace, target=box)
        return Response(BoxSerializer(box).data)


class ContainerContentsView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = GenericObjectSerializer

    @extend_schema(tags=["Containers"], summary="Get container contents", request=None, responses={200: ContainerContentsSerializer})
    def get(self, request, pk, *args, **kwargs):
        queryset = _with_active_box_qr(
            rbac.scope_by_action(request.user, rbac.Action.VIEW_INVENTORY, Box.objects.all())
        )
        box = get_object_or_404(queryset, pk=pk)
        require_module(box.makerspace, "containers")
        children = _with_active_box_qr(box.children.all()).order_by("label")
        return Response(
            {
                "container": BoxSerializer(box).data,
                "products": [
                    {"id": p.id, "name": p.name, "available_quantity": p.available_quantity, "tracking_mode": p.tracking_mode}
                    for p in box.products.filter(is_archived=False).order_by("name")
                ],
                "assets": [
                    {"id": a.id, "asset_tag": a.asset_tag, "product": a.product.name, "status": a.status}
                    for a in box.assets.select_related("product").order_by("asset_tag")
                ],
                "children": BoxSerializer(children, many=True).data,
            }
        )


class ContainerHistoryView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = GenericObjectSerializer

    @extend_schema(tags=["Containers"], summary="Get container scan history", request=None, responses={200: ContainerHistorySerializer})
    def get(self, request, pk, *args, **kwargs):
        box = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.VIEW_INVENTORY, Box.objects.all()), pk=pk)
        require_module(box.makerspace, "containers")
        qr_scans = [
            {
                "id": f"qr:{scan.id}",
                "source": "qr_scan_event",
                "context": scan.context,
                "actor": scan.actor_id,
                "created_at": scan.created_at,
            }
            for scan in QrScanEvent.objects.filter(
                makerspace=box.makerspace,
                qr_code__target_type=QrCode.TargetType.BOX,
                qr_code__target_id=box.id,
            ).order_by("-created_at")[:100]
        ]
        box_scans = [
            {
                "id": f"box:{scan.id}",
                "source": "box_scan",
                "context": scan.context,
                "actor": scan.actor_id,
                "created_at": scan.created_at,
            }
            for scan in BoxScan.objects.filter(
                makerspace=box.makerspace,
                box=box,
            ).order_by("-created_at")[:100]
        ]
        scans = sorted(
            [*qr_scans, *box_scans],
            key=lambda scan: scan["created_at"],
            reverse=True,
        )[:100]
        return Response({"container": box.id, "scans": scans})
