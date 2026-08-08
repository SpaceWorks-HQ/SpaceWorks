from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.warranty.serializers import (
    WarrantyDocumentFinalizeSerializer,
    WarrantyDocumentPresignSerializer,
    WarrantyDocumentSerializer,
    WarrantyDocumentUploadResponseSerializer,
    WarrantyDocumentUrlSerializer,
)
from apps.warranty.access import enforce, resolve_document, resolve_warranty
from apps.audit import services as audit
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.warranty import storage
from apps.warranty.models import WarrantyDocument


class WarrantyDocumentPresignView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin warranty"],
        summary="Create a warranty document upload URL",
        request=WarrantyDocumentPresignSerializer,
        responses={
            201: WarrantyDocumentUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid document upload request."),
            503: OpenApiResponse(description="Warranty document storage is unavailable."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        warranty = resolve_warranty(request.user, pk)
        enforce(request.user, warranty)
        serializer = WarrantyDocumentPresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ext = storage.ext_for(data["content_type"], data["filename"])
        object_key = storage.warranty_object_key(warranty.makerspace_id, ext)
        try:
            upload = storage.presigned_upload(object_key, data["content_type"])
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            {"object_key": object_key, "upload": upload},
            status=status.HTTP_201_CREATED,
        )


class WarrantyDocumentCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin warranty"],
        summary="List documents attached to a warranty",
        responses={200: WarrantyDocumentSerializer(many=True)},
    )
    def get(self, request, pk, *args, **kwargs):
        warranty = resolve_warranty(request.user, pk)
        enforce(request.user, warranty)
        documents = warranty.documents.order_by("-created_at", "-id")
        return Response(WarrantyDocumentSerializer(documents, many=True).data)

    @extend_schema(
        tags=["Admin warranty"],
        summary="Finalize an uploaded warranty document",
        request=WarrantyDocumentFinalizeSerializer,
        responses={
            201: WarrantyDocumentSerializer,
            400: OpenApiResponse(description="Invalid or duplicate warranty document."),
            503: OpenApiResponse(description="Warranty document storage is unavailable."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        warranty = resolve_warranty(request.user, pk)
        enforce(request.user, warranty)
        serializer = WarrantyDocumentFinalizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        object_key = data["object_key"]
        storage.assert_warranty_object_key_for_makerspace(
            object_key,
            warranty.makerspace_id,
        )
        if WarrantyDocument.objects.filter(object_key=object_key).exists():
            raise ValidationError({"object_key": "This warranty document is already attached."})
        try:
            storage.finalize_upload(object_key, settings.WARRANTY_DOC_MAX_BYTES)
            result = storage.validate_warranty_object(object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        document = WarrantyDocument.objects.create(
            warranty=warranty,
            object_key=object_key,
            original_filename=data["original_filename"],
            content_type=result.content_type,
            size_bytes=result.size,
            uploaded_by=request.user,
        )
        audit.record(
            request.user,
            "warranty.document_added",
            makerspace=warranty.makerspace,
            target=document,
        )
        return Response(
            WarrantyDocumentSerializer(document).data,
            status=status.HTTP_201_CREATED,
        )


class WarrantyDocumentUrlView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin warranty"],
        summary="Create a signed warranty document view URL",
        responses={
            200: WarrantyDocumentUrlSerializer,
            503: OpenApiResponse(description="Warranty document storage is unavailable."),
        },
    )
    def get(self, request, pk, *args, **kwargs):
        document = resolve_document(request.user, pk)
        enforce(request.user, document.warranty)
        try:
            url = storage.presigned_get_url(document.object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response({"url": url})


class WarrantyDocumentDeleteView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin warranty"],
        summary="Delete a warranty document",
        responses={204: None},
    )
    def delete(self, request, pk, *args, **kwargs):
        document = resolve_document(request.user, pk)
        warranty = document.warranty
        enforce(request.user, warranty)
        audit.record(
            request.user,
            "warranty.document_removed",
            makerspace=warranty.makerspace,
            target=document,
        )
        # The post_delete signal removes the stored object (covers every delete path,
        # including host/warranty CASCADE), so we don't delete it explicitly here.
        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
