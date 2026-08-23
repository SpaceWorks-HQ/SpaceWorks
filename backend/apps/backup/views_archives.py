from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, IsActiveSuperAdmin, require_action
from apps.backup import services, storage
from apps.backup.models import ARCHIVE_PURGE_WARNING, BackupArchive
from apps.backup.serializers import (
    BackupArchiveCreateSerializer,
    BackupArchiveSerializer,
    BackupDownloadSerializer,
)
from apps.backup.tasks import run_backup_archive_task
from apps.backup.views_common import AUTH_ERRORS, NOT_FOUND, VALIDATION_ERROR
from apps.makerspaces.models import Makerspace


class DeploymentArchiveListCreateView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=["Backup"], summary="List full-deployment backup archives", responses={200: BackupArchiveSerializer(many=True), **AUTH_ERRORS})
    def get(self, request):
        rows = BackupArchive.objects.filter(
            scope=BackupArchive.Scope.DEPLOYMENT
        ).exclude(
            status__in=(BackupArchive.Status.PENDING, BackupArchive.Status.RUNNING)
        )[:30]
        return Response(BackupArchiveSerializer(rows, many=True).data)

    @extend_schema(tags=["Backup"], summary="Request an age-encrypted full-deployment backup", request=BackupArchiveCreateSerializer, responses={202: BackupArchiveSerializer, 503: OpenApiResponse(description="The backup worker is unavailable."), **AUTH_ERRORS})
    def post(self, request):
        archive = services.create_archive(request.user, scope=BackupArchive.Scope.DEPLOYMENT)
        if not _dispatch(archive):
            return Response(BackupArchiveSerializer(archive).data, status=503)
        return Response(BackupArchiveSerializer(archive).data, status=status.HTTP_202_ACCEPTED)


class MakerspaceArchiveListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    def _makerspace(self, request, makerspace_id):
        require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
        return get_object_or_404(Makerspace, pk=makerspace_id)

    @extend_schema(tags=["Backup"], summary="List makerspace backup archives", responses={200: BackupArchiveSerializer(many=True), 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request, makerspace_id):
        makerspace = self._makerspace(request, makerspace_id)
        rows = BackupArchive.objects.filter(
            scope=BackupArchive.Scope.MAKERSPACE, makerspace=makerspace
        ).exclude(
            status__in=(BackupArchive.Status.PENDING, BackupArchive.Status.RUNNING)
        )[:30]
        return Response(BackupArchiveSerializer(rows, many=True).data)

    @extend_schema(tags=["Backup"], summary="Request an age-encrypted makerspace backup", request=BackupArchiveCreateSerializer, responses={202: BackupArchiveSerializer, 404: NOT_FOUND, 503: OpenApiResponse(description="The backup worker is unavailable."), **AUTH_ERRORS})
    def post(self, request, makerspace_id):
        makerspace = self._makerspace(request, makerspace_id)
        archive = services.create_archive(
            request.user, scope=BackupArchive.Scope.MAKERSPACE, makerspace=makerspace
        )
        if not _dispatch(archive):
            return Response(BackupArchiveSerializer(archive).data, status=503)
        return Response(BackupArchiveSerializer(archive).data, status=status.HTTP_202_ACCEPTED)


class BackupDownloadUrlView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Backup"], summary="Issue a one-use backup download URL", request=None, responses={200: BackupDownloadSerializer, 400: VALIDATION_ERROR, 404: NOT_FOUND, **AUTH_ERRORS})
    def post(self, request, archive_id):
        archive = get_object_or_404(BackupArchive.objects.select_related("makerspace"), pk=archive_id)
        if archive.scope == BackupArchive.Scope.DEPLOYMENT:
            if not (request.user.is_superuser or request.user.role == request.user.Role.SUPERADMIN):
                return Response({"detail": "Superadmin access is required."}, status=403)
        else:
            require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, archive.makerspace_id)
        token, expires_at = services.issue_download_token(archive, request.user)
        url = request.build_absolute_uri(reverse("backup-archive-download", args=(archive.pk, token)))
        return Response({"url": url, "expires_at": expires_at, "purge_warning": ARCHIVE_PURGE_WARNING})


class BackupArchiveDownloadView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(tags=["Backup"], summary="Consume a one-use backup download", auth=[], responses={200: OpenApiResponse(description="Age-encrypted archive stream."), 404: OpenApiResponse(description="Invalid or expired download.")})
    def get(self, request, archive_id, token):
        try:
            archive = services.consume_download_token(archive_id, token)
            body = storage.open_archive(archive.object_key)
        except (services.DownloadTokenError, storage.BackupStorageError):
            return Response({"detail": "The backup download is unavailable."}, status=404)
        response = StreamingHttpResponse(body.iter_chunks(), content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="spaceworks-{archive.scope}-{archive.id}.tar.age"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


def _dispatch(archive):
    try:
        run_backup_archive_task.delay(str(archive.pk))
        return True
    except Exception as exc:
        services.fail_archive_dispatch(archive, exc)
        archive.refresh_from_db()
        return False
