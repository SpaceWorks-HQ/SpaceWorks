from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied

from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.procurement.serializers import ToBuyItemSerializer
from apps.procurement import access
from apps.procurement.models import ToBuyItem
from apps.procurement.views_common import (
    KIND_PARAM,
    MODULE_KEY,
    PROCUREMENT_ERROR_RESPONSES,
    STATUS_PARAM,
    apply_status_filter,
    list_limit,
    receipt_queryset_related,
)


@extend_schema(tags=["Procurement"])
class ToBuyListCreateView(generics.ListCreateAPIView):
    serializer_class = ToBuyItemSerializer
    permission_classes = [IsActiveStaff]
    pagination_class = None

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(get_object_or_404(Makerspace, pk=makerspace_id), MODULE_KEY)
        limit = list_limit(self.request)
        queryset = access.scope_items(ToBuyItem.objects.all(), self.request.user, makerspace_id)
        queryset = apply_status_filter(queryset, self.request)
        return receipt_queryset_related(queryset).order_by("-created_at", "-id")[:limit]

    @extend_schema(
        summary="List to-buy items for a makerspace",
        parameters=[OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY), STATUS_PARAM],
        responses={200: ToBuyItemSerializer(many=True), **PROCUREMENT_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Add a to-buy item", parameters=[KIND_PARAM], responses={201: ToBuyItemSerializer, **PROCUREMENT_ERROR_RESPONSES})
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def perform_create(self, serializer):
        makerspace_id = self.kwargs["makerspace_id"]
        makerspace = get_object_or_404(Makerspace, pk=makerspace_id)
        require_module(makerspace, MODULE_KEY)
        if not access.can_use(self.request.user, makerspace_id):
            raise PermissionDenied()
        kind = access.derive_kind(
            self.request.user,
            makerspace_id,
            self.request.query_params.get("kind"),
        )
        machine_type = serializer.validated_data.get("machine_type")
        access.validate_machine_type(
            self.request.user,
            makerspace_id,
            kind,
            machine_type,
        )
        item = serializer.save(
            makerspace=makerspace,
            kind=kind,
            created_by=self.request.user,
        )
        audit.record(
            self.request.user,
            "procurement.item_added",
            makerspace=makerspace,
            target=item,
        )


@extend_schema(tags=["Procurement"])
class ToBuyDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ToBuyItemSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        makerspace_id = ToBuyItem.objects.filter(
            pk=self.kwargs.get("pk")
        ).values_list("makerspace_id", flat=True).first()
        queryset = receipt_queryset_related(ToBuyItem.objects.all())
        if makerspace_id is None:
            return queryset.none()
        return access.scope_items(
            queryset,
            self.request.user,
            makerspace_id,
        )

    def get_object(self):
        obj = super().get_object()
        require_module(obj.makerspace, MODULE_KEY)
        return get_object_or_404(
            access.scope_items(
                receipt_queryset_related(ToBuyItem.objects.all()),
                self.request.user,
                obj.makerspace_id,
            ),
            pk=obj.pk,
        )

    def _assert_can_manage(self, item):
        if not access.can_manage_kind(self.request.user, item.makerspace_id, item.kind):
            raise PermissionDenied()

    @extend_schema(summary="Retrieve a to-buy item", responses={200: ToBuyItemSerializer, **PROCUREMENT_ERROR_RESPONSES})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Update a to-buy item", request=ToBuyItemSerializer, responses={200: ToBuyItemSerializer, **PROCUREMENT_ERROR_RESPONSES})
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    @extend_schema(summary="Delete a to-buy item", responses={204: None, **PROCUREMENT_ERROR_RESPONSES})
    def delete(self, request, *args, **kwargs):
        return super().delete(request, *args, **kwargs)

    def perform_update(self, serializer):
        self._assert_can_manage(serializer.instance)
        machine_type = serializer.validated_data.get(
            "machine_type", serializer.instance.machine_type
        )
        access.validate_machine_type(
            self.request.user,
            serializer.instance.makerspace_id,
            serializer.instance.kind,
            machine_type,
        )
        access.validate_machine_type_provenance(serializer.instance, machine_type)
        previous_status = serializer.instance.status
        item = serializer.save()
        updates = []
        now = timezone.now()
        if previous_status != item.status and item.status == ToBuyItem.Status.ORDERED and item.ordered_at is None:
            item.ordered_at = now
            item.purchaser = self.request.user
            updates.extend(["ordered_at", "purchaser"])
        if previous_status != item.status and item.status == ToBuyItem.Status.RECEIVED and item.received_at is None:
            item.received_at = now
            updates.append("received_at")
            if item.purchaser_id is None:
                item.purchaser = self.request.user
                updates.append("purchaser")
        if updates:
            item.save(update_fields=[*updates, "updated_at"])
        audit.record(
            self.request.user,
            "procurement.item_updated",
            makerspace=item.makerspace,
            target=item,
        )

    def perform_destroy(self, instance):
        self._assert_can_manage(instance)
        audit.record(
            self.request.user,
            "procurement.item_removed",
            makerspace=instance.makerspace,
            target=instance,
        )
        instance.delete()


__all__ = [
    "KIND_PARAM",
    "MODULE_KEY",
    "PROCUREMENT_ERROR_RESPONSES",
    "STATUS_PARAM",
    "ToBuyDetailView",
    "ToBuyListCreateView",
    "receipt_queryset_related",
]
