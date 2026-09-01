from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.machine_access import resolve_machine
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_inventory import (
    PublicImageAttachRequestSerializer,
    PublicImageUploadRequestSerializer,
    PublicImageUploadResponseSerializer,
)
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage
from apps.machines import access, services
from apps.machines.serializers import MachineSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.limits import add_storage


class MachineImageView(APIView):
    permission_classes = [IsActiveStaff]

    def _machine(self, request, pk):
        machine = resolve_machine(request.user, pk)
        if not access.can_manage_machine(request.user, machine):
            raise PermissionDenied()
        require_module(machine.makerspace_id, "machines")
        return machine

    def _response(self, request, machine):
        return Response(MachineSerializer(machine, context={"request": request}).data)

    @extend_schema(
        tags=["Admin machines"],
        summary="Create a machine image upload URL",
        request=PublicImageUploadRequestSerializer,
        responses={
            201: PublicImageUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid image upload request."),
            403: OpenApiResponse(description="Machine management access is required."),
            404: OpenApiResponse(description="Machine not found."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        machine = self._machine(request, pk)
        serializer = PublicImageUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        ext = public_image_storage.ext_for(
            content_type,
            serializer.validated_data["filename"],
        )
        object_key = public_image_storage.build_object_key(
            "machine",
            machine.makerspace_id,
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
        tags=["Admin machines"],
        summary="Attach an uploaded image to a machine",
        request=PublicImageAttachRequestSerializer,
        responses={
            200: MachineSerializer,
            400: OpenApiResponse(description="Invalid image object key or size."),
            403: OpenApiResponse(description="Machine management access is required."),
            404: OpenApiResponse(description="Machine not found."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    @transaction.atomic
    def put(self, request, pk, *args, **kwargs):
        machine = self._machine(request, pk)
        serializer = PublicImageAttachRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        object_key = serializer.validated_data["object_key"]
        if not object_key.startswith(f"machine/{machine.makerspace_id}/"):
            raise ValidationError(
                {"object_key": "Image object key is outside this makerspace."}
            )
        if not public_image_storage.is_safe_object_key(object_key):
            raise ValidationError({"object_key": "Invalid image object key."})
        if object_key and public_image_storage.public_image_key_in_use(
            machine.makerspace_id,
            object_key,
            machine_id=machine.pk,
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
            raise ValidationError({"object_key": "Uploaded file is not a valid image."})
        old_key = machine.image_key
        if object_key != old_key:
            add_storage(machine.makerspace, result.size)
        machine = services.update_image(machine, request.user, object_key)
        return self._response(request, machine)

    @extend_schema(
        tags=["Admin machines"],
        summary="Clear a machine image",
        responses={
            200: MachineSerializer,
            403: OpenApiResponse(description="Machine management access is required."),
            404: OpenApiResponse(description="Machine not found."),
        },
    )
    def delete(self, request, pk, *args, **kwargs):
        machine = self._machine(request, pk)
        machine = services.remove_image(machine, request.user)
        return self._response(request, machine)
