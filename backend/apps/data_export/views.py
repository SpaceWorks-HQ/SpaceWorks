from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.data_export import services, storage
from apps.data_export.models import DataExportJob
from apps.data_export.serializers import (
    DataExportCreateSerializer,
    DataExportDownloadUrlSerializer,
    DataExportJobSerializer,
)
from apps.data_export.tasks import run_data_export_task
from apps.data_export.throttles import DataExportCreateThrottle
from apps.makerspaces.models import Makerspace


def _authorized_makerspace(actor, makerspace_id):
    makerspace = get_object_or_404(Makerspace, pk=makerspace_id)
    require_action(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk)
    return makerspace


class DataExportListCreateView(APIView):
    permission_classes = (IsActiveStaff,)

    @extend_schema(
        tags=["Data exports"],
        summary="List makerspace data-export jobs",
        responses={200: DataExportJobSerializer(many=True), 403: OpenApiResponse(description="MANAGE_MAKERSPACE is required.")},
    )
    def get(self, request, makerspace_id):
        _authorized_makerspace(request.user, makerspace_id)
        jobs = DataExportJob.objects.filter(makerspace_id=makerspace_id)[:20]
        return Response(DataExportJobSerializer(jobs, many=True).data)

    @extend_schema(
        tags=["Data exports"],
        summary="Request a redacted makerspace data export",
        request=DataExportCreateSerializer,
        responses={
            201: DataExportJobSerializer,
            400: OpenApiResponse(description="Invalid fidelity or quota/module policy failure."),
            403: OpenApiResponse(description="MANAGE_MAKERSPACE is required."),
            429: OpenApiResponse(description="Export creation rate limit exceeded."),
        },
    )
    def post(self, request, makerspace_id):
        makerspace = _authorized_makerspace(request.user, makerspace_id)
        serializer = DataExportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = services.create_export_job(request.user, makerspace)
        run_data_export_task.delay(str(job.pk))
        job.refresh_from_db()
        return Response(DataExportJobSerializer(job).data, status=status.HTTP_201_CREATED)

    def get_throttles(self):
        return [DataExportCreateThrottle()] if self.request.method == "POST" else []


class DataExportDetailView(APIView):
    permission_classes = (IsActiveStaff,)

    @extend_schema(
        tags=["Data exports"],
        summary="Poll a makerspace data-export job",
        responses={
            200: DataExportJobSerializer,
            403: OpenApiResponse(description="MANAGE_MAKERSPACE is required."),
            404: OpenApiResponse(description="Export job not found in this makerspace."),
        },
    )
    def get(self, request, makerspace_id, job_id):
        _authorized_makerspace(request.user, makerspace_id)
        job = get_object_or_404(
            DataExportJob, pk=job_id, makerspace_id=makerspace_id
        )
        return Response(DataExportJobSerializer(job).data)


class DataExportDownloadUrlView(APIView):
    permission_classes = (IsActiveStaff,)

    @extend_schema(
        tags=["Data exports"],
        summary="Issue a short-lived one-use export download URL",
        request=None,
        responses={
            200: DataExportDownloadUrlSerializer,
            400: OpenApiResponse(description="Export is not available."),
            403: OpenApiResponse(description="MANAGE_MAKERSPACE is required."),
            404: OpenApiResponse(description="Export job not found in this makerspace."),
        },
    )
    def post(self, request, makerspace_id, job_id):
        _authorized_makerspace(request.user, makerspace_id)
        job = get_object_or_404(
            DataExportJob, pk=job_id, makerspace_id=makerspace_id
        )
        raw, expires_at = services.issue_download_token(job, request.user)
        path = reverse(
            "data-export-download",
            kwargs={"job_id": job.pk, "token": raw},
        )
        payload = {"url": request.build_absolute_uri(path), "expires_at": expires_at}
        return Response(DataExportDownloadUrlSerializer(payload).data)


class DataExportDownloadView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    @extend_schema(
        tags=["Data exports"],
        summary="Consume a one-use export download URL",
        auth=[],
        responses={
            (200, "application/zip"): bytes,
            404: OpenApiResponse(description="Download link is invalid, expired, or used."),
            503: OpenApiResponse(description="Archive storage is unavailable."),
        },
    )
    def get(self, request, job_id, token):
        try:
            job = services.consume_download_token(job_id, token)
        except services.DownloadTokenError as exc:
            raise NotFound(str(exc)) from exc
        try:
            body = storage.open_archive(job.object_key)
        except storage.ExportStorageError:
            return Response(
                {"detail": "The export archive is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        filename = f"spaceworks-{job.makerspace.slug}-redacted-export.zip"
        response = FileResponse(body, content_type="application/zip", as_attachment=True, filename=filename)
        if job.accounted_size_bytes:
            response["Content-Length"] = str(job.accounted_size_bytes)
        response["Cache-Control"] = "private, no-store"
        return response
