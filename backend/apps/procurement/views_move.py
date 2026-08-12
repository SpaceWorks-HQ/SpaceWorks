from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.makerspaces.guards import require_module
from apps.procurement import access, services
from apps.procurement.models import ToBuyItem
from apps.procurement.serializers import (
    MoveToInventoryRequestSerializer,
    MoveToPrintingRequestSerializer,
    ToBuyItemSerializer,
)
from apps.procurement.views_common import (
    MODULE_KEY,
    PROCUREMENT_ERROR_RESPONSES,
    receipt_queryset_related,
)


class ToBuyMoveBaseView(APIView):
    permission_classes = [IsActiveStaff]

    def get_item(self, pk):
        makerspace_id = ToBuyItem.objects.filter(pk=pk).values_list(
            "makerspace_id", flat=True
        ).first()
        queryset = access.scope_items(
            receipt_queryset_related(ToBuyItem.objects.select_related("makerspace")),
            self.request.user,
            makerspace_id,
        ) if makerspace_id is not None else ToBuyItem.objects.none()
        item = get_object_or_404(queryset, pk=pk)
        require_module(item.makerspace, MODULE_KEY)
        if not access.can_manage_kind(self.request.user, item.makerspace_id, item.kind):
            raise PermissionDenied()
        return item

    def serialize_item(self, pk):
        item = get_object_or_404(receipt_queryset_related(ToBuyItem.objects.all()), pk=pk)
        return Response(ToBuyItemSerializer(item).data)


@extend_schema(tags=["Procurement"])
class ToBuyMoveToInventoryView(ToBuyMoveBaseView):
    @extend_schema(
        summary="Move a received hardware to-buy item into inventory",
        request=MoveToInventoryRequestSerializer,
        responses={200: ToBuyItemSerializer, **PROCUREMENT_ERROR_RESPONSES},
    )
    def post(self, request, pk, *args, **kwargs):
        item = self.get_item(pk)
        require_module(item.makerspace, "staff_admin")
        serializer = MoveToInventoryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.move_to_inventory(
            request.user,
            item,
            mode=data["mode"],
            product_id=data.get("product_id"),
            quantity=data["quantity"],
            box_id=data.get("box"),
            category_id=data.get("category"),
            tracking_mode=data.get("tracking_mode"),
            is_public=data["is_public"],
            public_availability_mode=data["public_availability_mode"],
            show_public_count=data["show_public_count"],
            public_self_checkout_enabled=data["public_self_checkout_enabled"],
            name=data.get("name"),
            description=data.get("description", ""),
        )
        return self.serialize_item(pk)


@extend_schema(tags=["Procurement"])
class ToBuyMoveToPrintingView(ToBuyMoveBaseView):
    @extend_schema(
        summary="Move a received printing to-buy item into printing assets",
        request=MoveToPrintingRequestSerializer,
        responses={200: ToBuyItemSerializer, **PROCUREMENT_ERROR_RESPONSES},
    )
    def post(self, request, pk, *args, **kwargs):
        item = self.get_item(pk)
        require_module(item.makerspace, "printing")
        serializer = MoveToPrintingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        target = data.pop("target")
        services.move_to_printing(request.user, item, target=target, data=data)
        return self.serialize_item(pk)
