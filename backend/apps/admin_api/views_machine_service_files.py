"""Staff-only private attachment endpoints for machine service requests."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_machine_service import (
    ServiceFileFinalizeSerializer,
    ServiceFileFinalizeResponseSerializer,
    ServiceFilePresignResponseSerializer,
    ServiceFilePresignSerializer,
    ServiceFileUrlSerializer,
)
from apps.admin_api.views_machine_service import _manageable_request
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.machines import role_scope, service_storage
from apps.machines.models import ServiceRequestFile
from apps.makerspaces.guards import require_module


FILE_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid attachment input."),
    401: OpenApiResponse(description="Authentication required."),
    403: OpenApiResponse(description="Machine management permission required."),
    404: OpenApiResponse(description="Service request or file was not found."),
    409: OpenApiResponse(ErrorSerializer, description="Attachment conflict."),
    503: OpenApiResponse(description="Private storage is unavailable."),
}


def _manageable_file(actor, pk, *, attached=False):
    visible = get_object_or_404(
        rbac.scope_by_makerspace(
            actor,
            ServiceRequestFile.objects.select_related("makerspace", "machine__makerspace", "service_request"),
            makerspace_field="makerspace_id",
        ),
        pk=pk,
    )
    require_module(visible.makerspace, "machine_service")
    if not rbac.can(actor, rbac.Action.MANAGE_MACHINES, visible.makerspace_id):
        raise PermissionDenied()
    field = "makerspace_id"
    scoped_files = ServiceRequestFile.objects.select_related(
        "makerspace", "machine__makerspace", "service_request__makerspace"
    )
    if attached:
        scoped_files = scoped_files.filter(service_request__isnull=False, attached_at__isnull=False)
    scoped_files = rbac.scope_by_action(
        actor, rbac.Action.MANAGE_MACHINES, scoped_files, field=field,
    )
    # A service file is the requester's uploaded design. It follows the machine that will
    # run it, so a role scoped to the laser cutters cannot pull down printer CAD.
    scoped_files = _narrow_files_to_machine_scope(actor, scoped_files)
    return get_object_or_404(scoped_files, pk=visible.pk)


def _narrow_files_to_machine_scope(actor, queryset):
    manage_scope = rbac.makerspaces_for_action(actor, rbac.Action.MANAGE_MACHINES)
    if manage_scope is rbac.ALL:
        return queryset
    return queryset.filter(
        role_scope.scoped_related_q(
            actor,
            manage_scope,
            # Two routes to a machine: the file may name one directly, or reach one
            # through the request it is attached to.
            machine_id_paths=(
                "machine_id",
                "service_request__assigned_machine_id",
                "service_request__bucket__machine_id",
            ),
            type_id_paths=(
                "machine__machine_type_id",
                "service_request__assigned_machine__machine_type_id",
                "service_request__bucket__machine__machine_type_id",
                "service_request__queue__machine_type_id",
            ),
        )
    ).distinct()


class MachineServiceFilePresignView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machine service"], summary="Create a service attachment upload URL",
        request=ServiceFilePresignSerializer,
        responses={201: ServiceFilePresignResponseSerializer, **FILE_ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        service_request = _manageable_request(request.user, pk)
        serializer = ServiceFilePresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            upload, presigned = service_storage.create_staged_file(
                service_request, actor=request.user, **serializer.validated_data,
            )
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response({"file_id": upload.pk, "upload": presigned}, status=status.HTTP_201_CREATED)


class MachineServiceFileFinalizeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machine service"], summary="Finalize a service attachment upload",
        request=ServiceFileFinalizeSerializer,
        responses={201: ServiceFileFinalizeResponseSerializer, **FILE_ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        service_request = _manageable_request(request.user, pk)
        serializer = ServiceFileFinalizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            file = service_storage.finalize_file(
                service_request, actor=request.user, **serializer.validated_data,
            )
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response({"file_id": file.pk}, status=status.HTTP_201_CREATED)


class MachineServiceFileUrlView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machine service"], summary="Create a signed service attachment URL",
        request=None, responses={200: ServiceFileUrlSerializer, **FILE_ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        file = _manageable_file(request.user, pk, attached=True)
        if file.service_request_id is None or file.attached_at is None:
            return Response({"detail": "Attachment is not available."}, status=status.HTTP_409_CONFLICT)
        try:
            url = service_storage.presigned_get_url(file.object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response({"url": url})


class MachineServiceFileDeleteView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machine service"], summary="Delete a staged service attachment",
        request=None, responses={204: None, **FILE_ERRORS},
    )
    def delete(self, request, pk, *args, **kwargs):
        file = _manageable_file(request.user, pk)
        try:
            service_storage.delete_staged_file(file, actor=request.user)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(status=status.HTTP_204_NO_CONTENT)
