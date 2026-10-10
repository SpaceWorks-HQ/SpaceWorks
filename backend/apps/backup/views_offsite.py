"""Superadmin API for offsite backup destinations. Deployment-level; never module-gated."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.audit import services as audit
from apps.backup.models import BackupArchive, BackupDestination, BackupDestinationUpload
from apps.backup.offsite_restore import validate_rehydration
from apps.backup.serializers_offsite import (
    BackupDestinationSerializer,
    BackupDestinationUploadSerializer,
    BackupDestinationPageSerializer,
    BackupDestinationUploadPageSerializer,
    DestinationDispatchSerializer,
    DestinationProbeSerializer,
    RehydrateSerializer,
    audit_meta,
)
from apps.backup.services_offsite import probe_destination, retire_destination
from apps.backup.tasks_offsite import dispatch_offsite_push, rehydrate_backup_archive_task
from apps.backup.views_common import AUTH_ERRORS, NOT_FOUND, VALIDATION_ERROR

TAGS = ["Backup destinations"]
PAGE = [OpenApiParameter("page", int, description="Page number (24 rows per page).")]


def _page(rows, request, serializer):
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(rows, request)
    return paginator.get_paginated_response(serializer(page, many=True).data)


class BackupDestinationListCreateView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="List offsite backup destinations", parameters=PAGE, responses={200: BackupDestinationPageSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request):
        rows = BackupDestination.objects.all()
        return _page(rows, request, BackupDestinationSerializer)

    @extend_schema(tags=TAGS, summary="Register an S3-compatible offsite backup destination", request=BackupDestinationSerializer, responses={201: BackupDestinationSerializer, 400: VALIDATION_ERROR, **AUTH_ERRORS})
    def post(self, request):
        serializer = BackupDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            destination = serializer.save(created_by=request.user)
            audit.record(
                request.user, "backup.destination_created", target=destination,
                meta=audit_meta(serializer.validated_data),
            )
        return Response(BackupDestinationSerializer(destination).data, status=status.HTTP_201_CREATED)


class BackupDestinationDetailView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="Get one offsite backup destination", responses={200: BackupDestinationSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request, destination_id):
        return Response(BackupDestinationSerializer(get_object_or_404(BackupDestination, pk=destination_id)).data)

    @extend_schema(tags=TAGS, summary="Update or rotate credentials of an offsite destination", request=BackupDestinationSerializer, responses={200: BackupDestinationSerializer, 400: VALIDATION_ERROR, 404: NOT_FOUND, **AUTH_ERRORS})
    def patch(self, request, destination_id):
        with transaction.atomic():
            destination = get_object_or_404(
                BackupDestination.objects.select_for_update(), pk=destination_id
            )
            serializer = BackupDestinationSerializer(destination, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            destination = serializer.save()
            audit.record(
                request.user, "backup.destination_updated", target=destination,
                meta=audit_meta(serializer.validated_data),
            )
        return Response(BackupDestinationSerializer(destination).data)


class BackupDestinationRetireView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="Retire a destination: stop pushing and wipe its stored credentials", request=None, responses={200: BackupDestinationSerializer, 400: VALIDATION_ERROR, 404: NOT_FOUND, **AUTH_ERRORS})
    def post(self, request, destination_id):
        get_object_or_404(BackupDestination, pk=destination_id)
        destination = retire_destination(destination_id, request.user)
        return Response(BackupDestinationSerializer(destination).data)


class BackupDestinationProbeView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="Probe write, read-back and delete on a destination", request=None, responses={200: DestinationProbeSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def post(self, request, destination_id):
        destination = get_object_or_404(
            BackupDestination, pk=destination_id, retired_at__isnull=True
        )
        return Response(probe_destination(destination, request.user))


class BackupDestinationUploadListView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="List the upload journal of one destination", parameters=PAGE, responses={200: BackupDestinationUploadPageSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request, destination_id):
        destination = get_object_or_404(BackupDestination, pk=destination_id)
        rows = BackupDestinationUpload.objects.filter(destination=destination).select_related("destination").order_by("-created_at", "-pk")
        return _page(rows, request, BackupDestinationUploadSerializer)


class BackupDestinationPushView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="Start an offsite push now instead of waiting for the schedule", request=None, responses={202: DestinationDispatchSerializer, 503: OpenApiResponse(description="The backup worker is unavailable."), **AUTH_ERRORS})
    def post(self, request):
        audit.record(request.user, "backup.offsite_push_requested", target=None, meta={})
        if not dispatch_offsite_push():
            return Response({"detail": "The backup worker is unavailable."}, status=503)
        return Response({"detail": "Offsite push dispatched."}, status=status.HTTP_202_ACCEPTED)


class BackupArchiveRehydrateView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="Restore an archive's primary bytes from a verified offsite copy", request=RehydrateSerializer, responses={202: DestinationDispatchSerializer, 400: VALIDATION_ERROR, 404: NOT_FOUND, 503: OpenApiResponse(description="The backup worker is unavailable."), **AUTH_ERRORS})
    def post(self, request, archive_id):
        archive = get_object_or_404(BackupArchive, pk=archive_id)
        serializer = RehydrateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        destination = serializer.validated_data["destination"]
        validate_rehydration(archive, destination)
        audit.record(
            request.user, "backup.archive_rehydrate_requested", target=archive,
            meta={"destination_id": destination.pk},
        )
        try:
            rehydrate_backup_archive_task.delay(str(archive.pk), destination.pk, request.user.pk)
        except Exception:
            return Response({"detail": "The backup worker is unavailable."}, status=503)
        return Response({"detail": "Rehydration dispatched."}, status=status.HTTP_202_ACCEPTED)
