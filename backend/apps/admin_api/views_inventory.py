from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView


class InventoryPagination(PageNumberPagination):
    # Opt-in larger pages (?page_size=) so pickers that need the full product list
    # (e.g. direct handout / transfers) aren't limited to the default first 24.
    page_size_query_param = "page_size"
    max_page_size = 1000

from apps.accounts import rbac
from apps.admin_api.inventory_filters import apply_inventory_list_filters
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.admin_api.serializers_inventory import (
    InventoryProductAdminCreateSerializer,
    InventoryProductAdminSerializer,
    InventoryProductAdminUpdateSerializer,
    PublicImageAttachRequestSerializer,
    PublicImageUploadRequestSerializer,
    PublicImageUploadResponseSerializer,
    InventoryQuantityAdjustmentSerializer,
)
from apps.audit import services as audit
from apps.inventory import availability
from apps.inventory import public_image_storage
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.inventory.models import InventoryProduct
from apps.makerspaces.guards import require_module
from apps.makerspaces.limits import add_storage


@extend_schema(tags=["Admin inventory"], summary="List or create inventory products")
class InventoryListCreateView(generics.ListCreateAPIView):
    serializer_class = InventoryProductAdminSerializer
    permission_classes = [IsActiveStaff]
    pagination_class = InventoryPagination

    def get_serializer_class(self):
        if self.request.method == "POST":
            return InventoryProductAdminCreateSerializer
        return InventoryProductAdminSerializer

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "staff_admin")
        require_action(self.request.user, rbac.Action.VIEW_INVENTORY, makerspace_id)
        qs = InventoryProduct.objects.filter(makerspace_id=makerspace_id).order_by("name")
        return apply_inventory_list_filters(qs, self.request.query_params)

    def perform_create(self, serializer):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "staff_admin")
        require_action(self.request.user, rbac.Action.EDIT_INVENTORY, makerspace_id)
        _assert_box_in_makerspace(serializer.validated_data.get("box"), makerspace_id)
        _assert_category_in_makerspace(
            serializer.validated_data.get("category"), makerspace_id
        )
        instance = serializer.save(makerspace_id=makerspace_id)
        audit.record(
            self.request.user,
            "inventory.created",
            makerspace=instance.makerspace,
            target=instance,
        )


@extend_schema(tags=["Admin inventory"], summary="Retrieve or update inventory product")
class InventoryDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = InventoryProductAdminSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return InventoryProductAdminUpdateSerializer
        return InventoryProductAdminSerializer

    def get_queryset(self):
        action = (
            rbac.Action.EDIT_INVENTORY
            if self.request.method == "PATCH"
            else rbac.Action.VIEW_INVENTORY
        )
        return rbac.scope_by_action(self.request.user, action, InventoryProduct.objects.select_related("makerspace", "box"))

    def perform_update(self, serializer):
        _assert_box_in_makerspace(
            serializer.validated_data.get("box"), serializer.instance.makerspace_id
        )
        _assert_category_in_makerspace(
            serializer.validated_data.get("category"), serializer.instance.makerspace_id
        )
        instance = serializer.save()
        audit.record(
            self.request.user,
            "inventory.updated",
            makerspace=instance.makerspace,
            target=instance,
        )


class InventoryQuantityAdjustmentView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin inventory"],
        summary="Adjust inventory quantity buckets",
        request=InventoryQuantityAdjustmentSerializer,
        responses={200: InventoryProductAdminSerializer},
    )
    def post(self, request, pk, *args, **kwargs):
        product = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.VIEW_INVENTORY,
                InventoryProduct.objects.select_related("makerspace"),
            ),
            pk=pk,
        )
        require_module(product.makerspace_id, "staff_admin")
        require_action(request.user, rbac.Action.EDIT_INVENTORY, product.makerspace_id)
        serializer = InventoryQuantityAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            locked = availability.adjust_quantities(
                product,
                delta_available=data["delta_available"],
                delta_damaged=data["delta_damaged"],
                delta_lost=data["delta_lost"],
                reason=data["reason"],
                actor=request.user,
            )
        except availability.InsufficientStock as exc:
            raise ValidationError(str(exc)) from exc
        return Response(InventoryProductAdminSerializer(locked).data)


class InventoryProductImageView(APIView):
    permission_classes = [IsActiveStaff]

    def _product(self, request, pk):
        product = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.VIEW_INVENTORY,
                InventoryProduct.objects.select_related("makerspace"),
            ),
            pk=pk,
        )
        require_module(product.makerspace_id, "staff_admin")
        require_action(request.user, rbac.Action.EDIT_INVENTORY, product.makerspace_id)
        return product

    @extend_schema(
        tags=["Admin inventory"],
        summary="Create an inventory product image upload URL",
        request=PublicImageUploadRequestSerializer,
        responses={
            201: PublicImageUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid image upload request."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        product = self._product(request, pk)
        serializer = PublicImageUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        ext = public_image_storage.ext_for(
            content_type,
            serializer.validated_data["filename"],
        )
        object_key = public_image_storage.build_object_key(
            "items",
            product.makerspace_id,
            ext,
        )
        try:
            upload = public_image_storage.presigned_upload(object_key, content_type)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            PublicImageUploadResponseSerializer({"object_key": object_key, **upload}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["Admin inventory"],
        summary="Attach an uploaded image to an inventory product",
        request=PublicImageAttachRequestSerializer,
        responses={
            200: InventoryProductAdminSerializer,
            400: OpenApiResponse(description="Invalid image object key or size."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    @transaction.atomic
    def put(self, request, pk, *args, **kwargs):
        product = self._product(request, pk)
        serializer = PublicImageAttachRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        object_key = serializer.validated_data["object_key"]
        expected_prefix = f"items/{product.makerspace_id}/"
        if not object_key.startswith(expected_prefix):
            raise ValidationError({"object_key": "Image object key is outside this makerspace."})
        if not public_image_storage.is_safe_object_key(object_key):
            raise ValidationError({"object_key": "Invalid image object key."})
        if object_key and public_image_storage.public_image_key_in_use(
            product.makerspace_id,
            object_key,
            product_id=product.pk,
        ):
            raise ValidationError({"object_key": "This image is already in use."})
        try:
            result = public_image_storage.finalize_upload(object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        if result.status != "ok":
            if result.status in {"empty", "too_large"}:
                public_image_storage.delete_object(object_key)
                public_image_storage.delete_object(
                    public_image_storage.staging_key(object_key)
                )
            raise ValidationError(
                {"object_key": public_image_storage.finalize_error_message(result)}
            )
        try:
            is_valid_image = public_image_storage.sniff_is_valid_image(object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        if not is_valid_image:
            public_image_storage.delete_object(object_key)
            public_image_storage.delete_object(public_image_storage.staging_key(object_key))
            raise ValidationError(
                {"object_key": "Uploaded file is not a valid image."}
            )
        product = InventoryProduct.objects.select_for_update().select_related(
            "makerspace"
        ).get(pk=product.pk)
        if object_key and public_image_storage.public_image_key_in_use(
            product.makerspace_id,
            object_key,
            product_id=product.pk,
        ):
            raise ValidationError({"object_key": "This image is already in use."})
        old_key = product.image_key
        if object_key != old_key:
            add_storage(product.makerspace, result.size)
        if old_key and old_key != object_key:
            public_image_storage.release_public_image_on_commit(
                product.makerspace, old_key
            )
        product.image_key = object_key
        product.save(update_fields=["image_key", "updated_at"])
        audit.record(
            request.user,
            "inventory.image_attached",
            makerspace=product.makerspace,
            target=product,
        )
        return Response(InventoryProductAdminSerializer(product).data)

    @extend_schema(
        tags=["Admin inventory"],
        summary="Clear an inventory product image",
        responses={
            200: InventoryProductAdminSerializer,
        },
    )
    @transaction.atomic
    def delete(self, request, pk, *args, **kwargs):
        product = self._product(request, pk)
        product = InventoryProduct.objects.select_for_update().select_related(
            "makerspace"
        ).get(pk=product.pk)
        old_key = product.image_key
        if old_key:
            public_image_storage.release_public_image_on_commit(
                product.makerspace, old_key
            )
        product.image_key = ""
        product.save(update_fields=["image_key", "updated_at"])
        audit.record(
            request.user,
            "inventory.image_cleared",
            makerspace=product.makerspace,
            target=product,
        )
        return Response(InventoryProductAdminSerializer(product).data)


def _assert_box_in_makerspace(box, makerspace_id):
    """A product may only point at a box in its own makerspace (tenant isolation)."""
    if box is not None and box.makerspace_id != makerspace_id:
        raise ValidationError({"box": "Box belongs to a different makerspace."})


def _assert_category_in_makerspace(category, makerspace_id):
    """A product may only point at a category in its own makerspace."""
    if category is not None and category.makerspace_id != makerspace_id:
        raise ValidationError(
            {"category": "Category belongs to a different makerspace."}
        )
