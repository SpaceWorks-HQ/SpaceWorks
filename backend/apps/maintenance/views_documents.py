from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.maintenance.serializers import (
    MaintenanceDocumentFinalizeSerializer,
    MaintenanceDocumentPresignResponseSerializer,
    MaintenanceDocumentPresignSerializer,
    MaintenanceDocumentUrlSerializer,
    MaintenanceLogDocumentSerializer,
)
from apps.maintenance.views_shared import (
    resolve_document,
    resolve_log,
)
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.hardware_requests.view_helpers import (
    ERROR_400, ERROR_403, ERROR_404, ERROR_409, ERROR_503,
)
from apps.maintenance import services, storage
from apps.maintenance.exceptions import RetiredMachineMaintenance


SCOPED = {400: ERROR_400, 403: ERROR_403, 404: ERROR_404}
STORED = {**SCOPED, 409: ERROR_409, 503: ERROR_503}


def _require_active(machine):
    if not machine.is_active:
        raise RetiredMachineMaintenance("Machine is retired.")


class MaintenanceLogDocumentPresignView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Create a maintenance document upload URL",
        request=MaintenanceDocumentPresignSerializer,
        responses={200: MaintenanceDocumentPresignResponseSerializer, **STORED},
    )
    def post(self, request, pk, *args, **kwargs):
        log = resolve_log(request.user, pk)
        _require_active(log.machine)
        serializer = MaintenanceDocumentPresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ext = storage.ext_for(data["content_type"], data["filename"])
        object_key = storage.log_document_object_key(
            log.machine.makerspace_id, log.machine_id, ext,
        )
        try:
            upload = storage.presigned_upload(object_key, data["content_type"])
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response({"object_key": object_key, "upload": upload})


class MaintenanceLogDocumentFinalizeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Finalize a maintenance document upload",
        request=MaintenanceDocumentFinalizeSerializer,
        responses={201: MaintenanceLogDocumentSerializer, **STORED},
    )
    def post(self, request, pk, *args, **kwargs):
        log = resolve_log(request.user, pk)
        serializer = MaintenanceDocumentFinalizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            document = services.finalize_log_document(
                log,
                actor=request.user,
                object_key=serializer.validated_data["object_key"],
            )
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            MaintenanceLogDocumentSerializer(document).data,
            status=status.HTTP_201_CREATED,
        )


class MaintenanceLogDocumentUrlView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Create a private maintenance document URL",
        request=None,
        responses={200: MaintenanceDocumentUrlSerializer, **STORED},
    )
    def get(self, request, pk, *args, **kwargs):
        document = resolve_document(request.user, pk, manage=False)
        try:
            url = storage.presigned_get_url(document.object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response({"url": url})


class MaintenanceLogDocumentDetailView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["delete", "options"]

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Delete a maintenance document",
        request=None,
        responses={204: None, **STORED},
    )
    def delete(self, request, pk, *args, **kwargs):
        document = resolve_document(request.user, pk, manage=True)
        try:
            services.delete_log_document(document, actor=request.user)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(status=status.HTTP_204_NO_CONTENT)
