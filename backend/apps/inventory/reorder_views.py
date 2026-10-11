from django.db.models import F
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.inventory.models import InventoryProduct
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.procurement.serializers import ToBuyItemSerializer
from apps.procurement.services_drafts import create_reorder_draft

ERRORS = {code: ErrorSerializer for code in (400, 401, 403, 404)}


class ReorderSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryProduct
        fields = ["id", "name", "manufacturer", "model", "sku", "barcode", "supplier",
                  "available_quantity", "reorder_point", "reorder_quantity"]
        read_only_fields = fields


class ReorderDraftSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)


def _makerspace(actor, pk, action=rbac.Action.EDIT_INVENTORY):
    space = get_object_or_404(rbac.scope_by_action(
        actor, action, Makerspace.objects.all(), field="id",
    ), pk=pk)
    require_module(space, "staff_admin")
    require_action(actor, action, pk)
    return space


class ReorderSuggestionsView(generics.ListAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ReorderSuggestionSerializer

    @extend_schema(tags=["Admin inventory"], summary="List products at their reorder points",
                   request=None, responses={200: ReorderSuggestionSerializer(many=True), **ERRORS})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        space = _makerspace(self.request.user, self.kwargs["makerspace_id"], rbac.Action.VIEW_INVENTORY)
        return rbac.scope_by_action(self.request.user, rbac.Action.VIEW_INVENTORY,
            InventoryProduct.objects.filter(makerspace=space, is_archived=False, reorder_point__gt=0,
                                            available_quantity__lte=F("reorder_point"))).order_by("name", "pk")


class ReorderDraftView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin inventory"], summary="Create or reuse a procurement reorder draft",
                   request=ReorderDraftSerializer,
                   responses={200: ToBuyItemSerializer, 201: ToBuyItemSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        space = _makerspace(request.user, makerspace_id)
        serializer = ReorderDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, created = create_reorder_draft(request.user, space, serializer.validated_data["product_id"])
        return Response(ToBuyItemSerializer(item).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
