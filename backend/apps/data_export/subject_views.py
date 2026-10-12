"""Authenticated owner-only subject export API."""

import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.schemas_self_service import ACCOUNT_ERRORS as ERRORS
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_feature, require_module
from apps.makerspaces.member_activity_service import active_membership
from apps.makerspaces.models import Makerspace
from apps.presence.guard import MemberPresenceRequired

from . import storage
from .models import DataExportJob
from .serializers import DataExportDownloadUrlSerializer
from .subject_services import create_subject_export, own_jobs, signed_download
from .subject_tasks import run_subject_export_task

logger = logging.getLogger(__name__)


class SubjectExportCreateSerializer(serializers.Serializer):
    def run_validation(self, data=serializers.empty):
        # Reject null/scalar roots before DRF's field-level empty-value validation,
        # which otherwise produces a list where Serializer.errors needs a mapping.
        if not isinstance(data, dict) or data:
            raise serializers.ValidationError({
                "non_field_errors": ["Supply an empty object; identity comes from authentication."],
            })
        return super().run_validation(data)


class SubjectExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataExportJob
        fields = ("id", "status", "failure_code", "failure_detail", "expires_at",
                  "created_at", "completed_at", "manifest")
        read_only_fields = fields


class SubjectExportListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = SubjectExportSerializer(many=True)


class SubjectExportThrottle(SimpleRateThrottle):
    scope = "subject_export"
    rate = "1/day"

    def get_cache_key(self, request, view):
        if not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class SubjectExportBaseView(APIView):
    permission_classes = (IsAuthenticated,)

    def makerspace(self, request, makerspace_id):
        space = get_object_or_404(
            rbac.scope_by_makerspace(request.user, Makerspace.objects.all(), "id"),
            pk=makerspace_id,
        )
        require_module(space, "membership")
        require_module(space, "member_accounts")
        require_feature(space, "membership.self_export")
        if active_membership(request.user, makerspace_id) is None:
            raise MemberPresenceRequired()
        return space


class SubjectExportListView(SubjectExportBaseView):
    @extend_schema(tags=["Member account"], summary="List the caller's personal exports",
                   request=None, responses={200: SubjectExportListSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        self.makerspace(request, makerspace_id)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(own_jobs(request.user, makerspace_id), request, view=self)
        return paginator.get_paginated_response(SubjectExportSerializer(page, many=True).data)

    @extend_schema(tags=["Member account"], summary="Request a personal ZIP/JSON data export",
                   request={"application/json": {"type": "object", "additionalProperties": False}},
                   responses={202: SubjectExportSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        space = self.makerspace(request, makerspace_id)
        serializer = SubjectExportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Run this after authentication, tenant gates and payload validation. Custom
        # lifecycle hooks are forbidden on claim-reachable routes; the service also
        # enforces the daily limit under the tenant lock when the cache is cold.
        throttle = SubjectExportThrottle()
        if not throttle.allow_request(request, self):
            self.throttled(request, throttle.wait())
        job = create_subject_export(request.user, space)
        try:
            run_subject_export_task.delay(str(job.pk))
        except Exception:
            # Durable pending jobs are recovered by F1 even when the broker is down.
            logger.warning("subject_export_enqueue_failed", extra={"job_id": str(job.pk)})
        return Response(SubjectExportSerializer(job).data, status=202)


class SubjectExportDetailView(SubjectExportBaseView):
    @extend_schema(tags=["Member account"], summary="Poll the caller's personal export",
                   request=None, responses={200: SubjectExportSerializer, **ERRORS})
    def get(self, request, makerspace_id, job_id):
        self.makerspace(request, makerspace_id)
        job = get_object_or_404(own_jobs(request.user, makerspace_id), pk=job_id)
        return Response(SubjectExportSerializer(job).data)


class SubjectExportDownloadView(SubjectExportBaseView):
    @extend_schema(tags=["Member account"], summary="Sign a short-lived personal export download URL",
                   request=None, responses={200: DataExportDownloadUrlSerializer,
                   503: OpenApiResponse(ErrorSerializer, description="Object storage unavailable."), **ERRORS})
    def post(self, request, makerspace_id, job_id):
        self.makerspace(request, makerspace_id)
        job = get_object_or_404(own_jobs(request.user, makerspace_id), pk=job_id)
        try:
            payload = signed_download(job, request.user)
        except storage.ExportStorageError:
            return Response({"detail": "Export storage is temporarily unavailable.", "code": "storage_unavailable"}, status=503)
        response = Response(DataExportDownloadUrlSerializer(payload).data)
        response["Cache-Control"] = "private, no-store"
        return response
