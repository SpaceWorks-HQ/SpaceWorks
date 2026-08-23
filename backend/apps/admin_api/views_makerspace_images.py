from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.admin_api.serializers_inventory import (
    PublicImageAttachRequestSerializer,
    PublicImageUploadRequestSerializer,
    PublicImageUploadResponseSerializer,
)
from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
from apps.audit import services as audit
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage
from apps.makerspaces.limits import add_storage
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


class MakerspaceImageView(APIView):
    permission_classes = [IsActiveStaff]
    image_field = ""
    attach_action = ""
    clear_action = ""

    def _makerspace(self, request, makerspace_id):
        makerspace = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )
        require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id)
        return makerspace

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Create a makerspace public image upload URL",
        request=PublicImageUploadRequestSerializer,
        responses={
            201: PublicImageUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid image upload request."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = self._makerspace(request, makerspace_id)
        serializer = PublicImageUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        ext = public_image_storage.ext_for(
            content_type,
            serializer.validated_data["filename"],
        )
        object_key = public_image_storage.build_object_key(
            "makerspace", makerspace.id, ext
        )
        try:
            upload = public_image_storage.presigned_upload(object_key, content_type)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            PublicImageUploadResponseSerializer(
                {"object_key": object_key, **upload}
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Attach an uploaded public image to a makerspace",
        request=PublicImageAttachRequestSerializer,
        responses={
            200: MakerspaceSerializer,
            400: OpenApiResponse(description="Invalid image object key or size."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    @transaction.atomic
    def put(self, request, makerspace_id, *args, **kwargs):
        makerspace = self._makerspace(request, makerspace_id)
        serializer = PublicImageAttachRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        object_key = serializer.validated_data["object_key"]
        expected_prefix = f"makerspace/{makerspace.id}/"
        if not object_key.startswith(expected_prefix):
            raise ValidationError(
                {"object_key": "Image object key is outside this makerspace."}
            )
        if not public_image_storage.is_safe_object_key(object_key):
            raise ValidationError({"object_key": "Invalid image object key."})
        if object_key and public_image_storage.public_image_key_in_use(
            makerspace.id,
            object_key,
            makerspace_field=self.image_field,
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
            public_image_storage.delete_object(
                public_image_storage.staging_key(object_key)
            )
            raise ValidationError(
                {"object_key": "Uploaded file is not a valid image."}
            )
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if object_key and public_image_storage.public_image_key_in_use(
            makerspace.id,
            object_key,
            makerspace_field=self.image_field,
        ):
            raise ValidationError({"object_key": "This image is already in use."})
        old_key = getattr(makerspace, self.image_field)
        if object_key != old_key:
            add_storage(makerspace, result.size)
        if old_key and old_key != object_key:
            public_image_storage.release_public_image_on_commit(makerspace, old_key)
        setattr(makerspace, self.image_field, object_key)
        makerspace.save(update_fields=[self.image_field, "updated_at"])
        audit.record(
            request.user,
            self.attach_action,
            makerspace=makerspace,
            target=makerspace,
        )
        return Response(
            MakerspaceSerializer(makerspace, context={"request": request}).data
        )

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Clear a makerspace public image",
        responses={200: MakerspaceSerializer},
    )
    @transaction.atomic
    def delete(self, request, makerspace_id, *args, **kwargs):
        makerspace = self._makerspace(request, makerspace_id)
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        old_key = getattr(makerspace, self.image_field)
        if old_key:
            public_image_storage.release_public_image_on_commit(makerspace, old_key)
        setattr(makerspace, self.image_field, "")
        makerspace.save(update_fields=[self.image_field, "updated_at"])
        audit.record(
            request.user,
            self.clear_action,
            makerspace=makerspace,
            target=makerspace,
        )
        return Response(
            MakerspaceSerializer(makerspace, context={"request": request}).data
        )


class MakerspaceLogoImageView(MakerspaceImageView):
    image_field = "logo_key"
    attach_action = "makerspace.logo_attached"
    clear_action = "makerspace.logo_cleared"


class MakerspaceCoverImageView(MakerspaceImageView):
    image_field = "cover_image_key"
    attach_action = "makerspace.cover_attached"
    clear_action = "makerspace.cover_cleared"
