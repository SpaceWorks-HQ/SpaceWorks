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
from apps.events import services_series_images
from apps.events.serializers_series import EventSeriesDetailSerializer
from apps.events.views_series import manageable_series
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage


PREFIX = "event-series"
ERRORS = {
    400: OpenApiResponse(description="Invalid image upload request."),
    401: OpenApiResponse(description="Authentication required."),
    403: OpenApiResponse(description="Event management access is required."),
    404: OpenApiResponse(description="Event series not found."),
    429: OpenApiResponse(description="Rate limit exceeded."),
    503: OpenApiResponse(description="Public image storage is unavailable."),
}


class EventSeriesImageView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin event series"], summary="Create a series image upload URL",
        request=PublicImageUploadRequestSerializer,
        responses={201: PublicImageUploadResponseSerializer, **ERRORS},
    )
    def post(self, request, pk):
        series = manageable_series(request.user, pk)
        serializer = PublicImageUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        ext = public_image_storage.ext_for(content_type, serializer.validated_data["filename"])
        object_key = public_image_storage.build_object_key(PREFIX, series.makerspace_id, ext)
        try:
            upload = public_image_storage.presigned_upload(object_key, content_type)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            PublicImageUploadResponseSerializer({"object_key": object_key, **upload}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["Admin event series"], summary="Attach an uploaded series image",
        request=PublicImageAttachRequestSerializer,
        responses={200: EventSeriesDetailSerializer, **ERRORS},
    )
    @transaction.atomic
    def put(self, request, pk):
        series = manageable_series(request.user, pk)
        serializer = PublicImageAttachRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        object_key = serializer.validated_data["object_key"]
        if not object_key.startswith(f"{PREFIX}/{series.makerspace_id}/"):
            raise ValidationError({"object_key": "Image object key is outside this makerspace."})
        if not public_image_storage.is_safe_object_key(object_key):
            raise ValidationError({"object_key": "Invalid image object key."})
        if public_image_storage.public_image_key_in_use(
            series.makerspace_id, object_key, series_id=series.pk
        ):
            raise ValidationError({"object_key": "This image is already in use."})
        try:
            result = public_image_storage.finalize_upload(object_key)
            valid = result.status == "ok" and public_image_storage.sniff_is_valid_image(object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        if not valid:
            public_image_storage.delete_object(object_key)
            public_image_storage.delete_object(public_image_storage.staging_key(object_key))
            message = (
                "Uploaded file is not a valid image."
                if result.status == "ok"
                else public_image_storage.finalize_error_message(result)
            )
            raise ValidationError({"object_key": message})
        series = services_series_images.update_image(series, request.user, object_key)
        return Response(EventSeriesDetailSerializer(series).data)

    @extend_schema(
        tags=["Admin event series"], summary="Clear a series image",
        request=None, responses={200: EventSeriesDetailSerializer, **ERRORS},
    )
    def delete(self, request, pk):
        series = manageable_series(request.user, pk)
        series = services_series_images.remove_image(series, request.user)
        return Response(EventSeriesDetailSerializer(series).data)
