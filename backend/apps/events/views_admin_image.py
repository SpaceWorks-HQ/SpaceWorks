"""Event cover image upload/attach/clear, mirroring admin_api.views_machine_image.

Lives in apps.events rather than admin_api so an `events` tombstone withdraws it
with the rest of the app's surfaces.
"""

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_inventory import (
    PublicImageAttachRequestSerializer,
    PublicImageUploadRequestSerializer,
    PublicImageUploadResponseSerializer,
)
from apps.events import services_images
from apps.events.serializers_admin import EventAdminSerializer
from apps.events.views_admin import _manageable_event
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage

IMAGE_PREFIX = "event"


class EventImageView(APIView):
    permission_classes = [IsActiveStaff]

    def _response(self, request, event):
        return Response(
            EventAdminSerializer(event, context={"request": request}).data
        )

    @extend_schema(
        tags=["Admin events"],
        summary="Create an event image upload URL",
        request=PublicImageUploadRequestSerializer,
        responses={
            201: PublicImageUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid image upload request."),
            403: OpenApiResponse(description="Event management access is required."),
            404: OpenApiResponse(description="Event not found."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        serializer = PublicImageUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        ext = public_image_storage.ext_for(
            content_type,
            serializer.validated_data["filename"],
        )
        object_key = public_image_storage.build_object_key(
            IMAGE_PREFIX,
            event.makerspace_id,
            ext,
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
        tags=["Admin events"],
        summary="Attach an uploaded image to an event",
        request=PublicImageAttachRequestSerializer,
        responses={
            200: EventAdminSerializer,
            400: OpenApiResponse(description="Invalid image object key or size."),
            403: OpenApiResponse(description="Event management access is required."),
            404: OpenApiResponse(description="Event not found."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    @transaction.atomic
    def put(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        serializer = PublicImageAttachRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        object_key = serializer.validated_data["object_key"]
        # Prefix check first: it is what stops one makerspace attaching another's
        # object, and it must run before anything touches storage.
        if not object_key.startswith(f"{IMAGE_PREFIX}/{event.makerspace_id}/"):
            raise ValidationError(
                {"object_key": "Image object key is outside this makerspace."}
            )
        if not public_image_storage.is_safe_object_key(object_key):
            raise ValidationError({"object_key": "Invalid image object key."})
        if public_image_storage.public_image_key_in_use(
            event.makerspace_id,
            object_key,
            event_id=event.pk,
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
            raise ValidationError({"object_key": "Uploaded file is not a valid image."})
        event = services_images.update_image(event, request.user, object_key)
        return self._response(request, event)

    @extend_schema(
        tags=["Admin events"],
        summary="Clear an event image",
        responses={
            200: EventAdminSerializer,
            403: OpenApiResponse(description="Event management access is required."),
            404: OpenApiResponse(description="Event not found."),
        },
    )
    def delete(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        event = services_images.remove_image(event, request.user)
        return self._response(request, event)
