import logging

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.accounts import rbac
from apps.accounts.permissions import (
    HasMakerspaceAction,
    StaffAPIView,
)
from apps.accounts.models import User
from apps.audit import services as audit
from apps.evidence.models import EvidencePhoto
from apps.evidence.serializers import (
    EvidenceGetResponseSerializer,
    EvidenceUrlRequestSerializer,
    EvidenceUrlResponseSerializer,
)
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import (
    StorageUnavailable,
    evidence_object_key,
    object_exists,
    presigned_get_url,
    staging_key,
    presigned_upload,
)
from apps.makerspaces.models import Makerspace
from apps.makerspaces.guards import require_module

logger = logging.getLogger(__name__)


class ActiveAuthenticatedPermission(BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(
            getattr(user, "is_authenticated", False)
            and user.access_status == User.AccessStatus.ACTIVE
            and not getattr(user, "must_change_password", False)
        )


class EvidenceUploadUrlView(StaffAPIView):
    required_action = rbac.Action.UPLOAD_EVIDENCE
    permission_classes = [IsAuthenticated, HasMakerspaceAction]

    @extend_schema(
        request=EvidenceUrlRequestSerializer,
        responses={
            201: EvidenceUrlResponseSerializer,
            400: OpenApiResponse(description="Invalid evidence upload request."),
            403: OpenApiResponse(description="Insufficient makerspace permission."),
            503: OpenApiResponse(description="Evidence storage is unavailable."),
        },
    )
    def post(self, request, *args, **kwargs):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "evidence_uploads")
        serializer = EvidenceUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        evidence_type = serializer.validated_data["evidence_type"]
        content_type = serializer.validated_data["content_type"]
        size_bytes = serializer.validated_data.get("size_bytes")
        object_key = evidence_object_key(makerspace_id, evidence_type)

        try:
            upload = presigned_upload(object_key, content_type)
        except StorageUnavailable:
            logger.warning(
                "evidence_upload_url_storage_unavailable",
                extra={"makerspace_id": makerspace_id, "evidence_type": evidence_type},
                exc_info=True,
            )
            return storage_unavailable_response()

        with transaction.atomic():
            makerspace = get_object_or_404(Makerspace, pk=makerspace_id)
            photo = EvidencePhoto.objects.create(
                makerspace=makerspace,
                evidence_type=evidence_type,
                object_key=object_key,
                content_type=content_type,
                size_bytes=size_bytes,
                uploaded_by=request.user,
            )
            audit.record(
                request.user,
                "evidence.upload_url_issued",
                makerspace=makerspace,
                target=photo,
            )

        logger.info(
            "evidence_upload_url_issued",
            extra={
                "evidence_id": photo.pk,
                "makerspace_id": makerspace_id,
                "evidence_type": evidence_type,
            },
        )
        data = {
            "evidence_id": photo.pk,
            "upload_url": upload["url"],
            "fields": upload.get("fields", {}),
            "object_key": object_key,
        }
        if upload.get("method"):
            data["method"] = upload["method"]
            data["headers"] = upload.get("headers", {})
        return Response(EvidenceUrlResponseSerializer(data).data, status=201)


class EvidenceDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, ActiveAuthenticatedPermission]
    queryset = EvidencePhoto.objects.all()
    serializer_class = EvidenceGetResponseSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        qs = rbac.scope_by_action(
            self.request.user,
            rbac.Action.UPLOAD_EVIDENCE,
            qs,
        )
        return rbac.hide_from_superadmin(self.request.user, qs, "makerspace_id")

    @extend_schema(
        responses={
            200: EvidenceGetResponseSerializer,
            404: OpenApiResponse(description="Evidence was not found."),
            409: OpenApiResponse(description="Evidence object has not been uploaded."),
            503: OpenApiResponse(description="Evidence storage is unavailable."),
        },
    )
    def retrieve(self, request, *args, **kwargs):
        photo = self.get_object()
        require_module(photo.makerspace, "evidence_uploads")

        # A presigned upload lands on the staging key and only becomes the final,
        # never-client-writable object when a workflow promotes it. So an uploaded but
        # not-yet-consumed photo lives in staging, and a read that only ever HEADs the
        # final key would report it as never uploaded.
        try:
            readable_key = None
            if object_exists(photo.object_key):
                readable_key = photo.object_key
            elif object_exists(staging_key(photo.object_key)):
                readable_key = staging_key(photo.object_key)
        except StorageUnavailable:
            logger.warning(
                "evidence_head_storage_unavailable",
                extra={"evidence_id": photo.pk, "makerspace_id": photo.makerspace_id},
                exc_info=True,
            )
            return storage_unavailable_response()
        if readable_key is None:
            return Response(status=409)

        try:
            url = presigned_get_url(readable_key)
        except StorageUnavailable:
            logger.warning(
                "evidence_get_url_storage_unavailable",
                extra={"evidence_id": photo.pk, "makerspace_id": photo.makerspace_id},
                exc_info=True,
            )
            return storage_unavailable_response()

        audit.record(
            request.user,
            "evidence.viewed",
            makerspace=photo.makerspace,
            target=photo,
        )
        return Response(
            EvidenceGetResponseSerializer(
                {"url": url, "expires_in": settings.EVIDENCE_URL_TTL_SECONDS}
            ).data
        )
