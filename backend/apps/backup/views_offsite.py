"""Superadmin API for offsite backup destinations. Deployment-level; never module-gated."""

import uuid

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.audit import services as audit
from apps.backup import offsite_client
from apps.backup.models import BackupArchive, BackupDestination, BackupDestinationUpload
from apps.backup.offsite_restore import validate_rehydration
from apps.backup.serializers_offsite import (
    BackupDestinationSerializer,
    BackupDestinationUploadSerializer,
    DestinationProbeSerializer,
    RehydrateSerializer,
    audit_meta,
)
from apps.backup.tasks_offsite import dispatch_offsite_push, rehydrate_backup_archive_task
from apps.backup.views_common import AUTH_ERRORS, NOT_FOUND, VALIDATION_ERROR

TAGS = ["Backup destinations"]


class BackupDestinationListCreateView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="List offsite backup destinations", responses={200: BackupDestinationSerializer(many=True), **AUTH_ERRORS})
    def get(self, request):
        rows = BackupDestination.objects.all()
        return Response(BackupDestinationSerializer(rows, many=True).data)

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
        with transaction.atomic():
            destination = get_object_or_404(
                BackupDestination.objects.select_for_update(), pk=destination_id
            )
            if destination.retired_at is not None:
                return Response({"detail": "The destination is already retired."}, status=400)
            destination.enabled = False
            destination.retired_at = timezone.now()
            destination.set_access_key_id("")
            destination.set_secret_access_key("")
            destination.save()
            # The journal is history and stays; copies already on the destination are
            # outside this deployment's control once its credentials are gone.
            audit.record(
                request.user, "backup.destination_retired", target=destination,
                meta={"name": destination.name, "archives_outside_purge_guarantee": True},
            )
        return Response(BackupDestinationSerializer(destination).data)


class BackupDestinationProbeView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="Probe write, read-back and delete on a destination", request=None, responses={200: DestinationProbeSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def post(self, request, destination_id):
        destination = get_object_or_404(
            BackupDestination, pk=destination_id, retired_at__isnull=True
        )
        error_code = ""
        try:
            offsite_client.probe(destination, nonce=uuid.uuid4().hex)
        except offsite_client.OffsiteDestinationError as exc:
            error_code = exc.code
        audit.record(
            request.user, "backup.destination_probed", target=destination,
            meta={"ok": not error_code, "error_code": error_code},
        )
        return Response({"ok": not error_code, "error_code": error_code})


class BackupDestinationUploadListView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="List the upload journal of one destination", responses={200: BackupDestinationUploadSerializer(many=True), 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request, destination_id):
        destination = get_object_or_404(BackupDestination, pk=destination_id)
        rows = BackupDestinationUpload.objects.filter(destination=destination).select_related("destination")[:100]
        return Response(BackupDestinationUploadSerializer(rows, many=True).data)


class BackupDestinationPushView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="Start an offsite push now instead of waiting for the schedule", request=None, responses={202: OpenApiResponse(description="Push dispatched."), **AUTH_ERRORS})
    def post(self, request):
        audit.record(request.user, "backup.offsite_push_requested", target=None, meta={})
        dispatch_offsite_push()
        return Response({"detail": "Offsite push dispatched."}, status=status.HTTP_202_ACCEPTED)


class BackupArchiveRehydrateView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=TAGS, summary="Restore an archive's primary bytes from a verified offsite copy", request=RehydrateSerializer, responses={202: OpenApiResponse(description="Rehydration dispatched."), 400: VALIDATION_ERROR, 404: NOT_FOUND, 503: OpenApiResponse(description="The backup worker is unavailable."), **AUTH_ERRORS})
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
