from django.shortcuts import get_object_or_404
from django.urls import reverse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.admin_api.permissions import (
    IsActiveSuperAdmin,
    require_makerspace_superadmin_access,
)
from apps.audit import services as audit
from apps.data_export import services as export_services
from apps.data_export.models import DataExportJob
from apps.data_export.serializers import DataExportDownloadUrlSerializer
from apps.makerspaces.models import Makerspace

from . import admission
from .models_protocol import DisclosureClosureApproval
from .serializers import (
    ClosureApprovalCreateSerializer,
    ClosureApprovalSerializer,
    MigrationExportCreateSerializer,
    MigrationExportJobSerializer,
    PendingClosureSerializer,
)
from .services_export_job import create_migration_export_job
from .tasks import run_migration_export_job_task
from .views_common import AUTH_ERRORS, CONFLICT, FIELD_ERRORS, NOT_FOUND, protocol_error


class MigrationAPIView(APIView):
    permission_classes = [IsActiveSuperAdmin]
    throttle_classes = [ScopedRateThrottle]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        makerspace_id = self.kwargs.get("makerspace_id")
        if makerspace_id is not None:
            self.makerspace = get_object_or_404(Makerspace, pk=makerspace_id)
            require_makerspace_superadmin_access(request.user, self.makerspace)

    def get_throttles(self):
        self.throttle_scope = (
            "tenant_migration_read"
            if self.request.method in {"GET", "HEAD"}
            else "tenant_migration_write"
        )
        return super().get_throttles()

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        codes = {
            status.HTTP_401_UNAUTHORIZED: "not_authenticated",
            status.HTTP_403_FORBIDDEN: "permission_denied",
            status.HTTP_404_NOT_FOUND: "not_found",
            status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
        }
        if (
            response.status_code in codes
            and isinstance(response.data, dict)
            and "detail" in response.data
        ):
            response.data = {
                "detail": str(response.data["detail"]),
                "code": codes[response.status_code],
            }
        return response


class DisclosureClosureView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Compute the pending PORTABLE disclosure closure", responses={200: PendingClosureSerializer, **AUTH_ERRORS})
    def get(self, request, makerspace_id):
        space = self.makerspace
        closure = admission.compute_pending_closure(space)
        audit.record(
            request.user, "tenant_migration.disclosure_computed", makerspace=space,
            target=space, meta={
                "closure_digest": closure["digest"],
                "identity_count": len(closure["identities"]), "format_version": 1,
            },
        )
        return Response(PendingClosureSerializer(closure).data)


class DisclosureApprovalListCreateView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="List disclosure approvals", responses={200: ClosureApprovalSerializer(many=True), **AUTH_ERRORS})
    def get(self, request, makerspace_id):
        space = self.makerspace
        rows = DisclosureClosureApproval.objects.filter(makerspace=space)[:20]
        audit.record(
            request.user, "tenant_migration.disclosure_approvals_read",
            makerspace=space, target=space,
            meta={"approval_count": len(rows), "format_version": 1},
        )
        return Response(ClosureApprovalSerializer(rows, many=True).data)

    @extend_schema(tags=["Tenant migration"], summary="Approve each identity in one exact disclosure closure", request=ClosureApprovalCreateSerializer, responses={201: ClosureApprovalSerializer, 400: FIELD_ERRORS, 409: CONFLICT, **AUTH_ERRORS})
    def post(self, request, makerspace_id):
        space = self.makerspace
        serializer = ClosureApprovalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = admission.approve_closure(
                actor=request.user, makerspace=space, **serializer.validated_data
            )
        except Exception as exc:
            return protocol_error(exc)
        return Response(ClosureApprovalSerializer(row).data, status=status.HTTP_201_CREATED)


class DisclosureApprovalRevokeView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Revoke a disclosure approval", request=None, responses={200: ClosureApprovalSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def post(self, request, makerspace_id, approval_id):
        row = get_object_or_404(
            DisclosureClosureApproval, pk=approval_id, makerspace_id=makerspace_id
        )
        return Response(ClosureApprovalSerializer(
            admission.revoke_approval(actor=request.user, approval=row)
        ).data)


class MigrationExportListCreateView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="List PORTABLE migration export jobs", responses={200: MigrationExportJobSerializer(many=True), **AUTH_ERRORS})
    def get(self, request, makerspace_id):
        space = get_object_or_404(Makerspace, pk=makerspace_id)
        rows = DataExportJob.objects.filter(
            makerspace_id=makerspace_id, fidelity="PORTABLE",
            migration_export__isnull=False,
        ).select_related("migration_export")[:20]
        audit.record(
            request.user, "tenant_migration.exports_read", makerspace=space, target=space,
            meta={"export_count": len(rows), "format_version": 1},
        )
        return Response(MigrationExportJobSerializer(rows, many=True).data)

    @extend_schema(tags=["Tenant migration"], summary="Create a target-recipient-encrypted PORTABLE export", request=MigrationExportCreateSerializer, responses={202: MigrationExportJobSerializer, 400: FIELD_ERRORS, 409: CONFLICT, 503: OpenApiResponse(description="Migration worker unavailable."), **AUTH_ERRORS})
    def post(self, request, makerspace_id):
        serializer = MigrationExportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        space = self.makerspace
        approval = get_object_or_404(
            DisclosureClosureApproval,
            pk=serializer.validated_data["approval_id"], makerspace=space,
        )
        try:
            job = create_migration_export_job(
                actor=request.user, makerspace=space, approval=approval,
                target_age_recipient=serializer.validated_data["target_age_recipient"],
            )
        except Exception as exc:
            return protocol_error(exc)
        try:
            run_migration_export_job_task.delay(str(job.pk))
        except Exception:
            export_services._fail_job(
                job, DataExportJob.FailureCode.INTERNAL_ERROR,
                "The migration export worker is unavailable.",
            )
            job.refresh_from_db()
            return Response(
                {"detail": "The migration export worker is unavailable.", "code": "worker_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        job.refresh_from_db()
        return Response(MigrationExportJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class MigrationExportDetailView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Read a PORTABLE migration export job", responses={200: MigrationExportJobSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request, makerspace_id, job_id):
        job = get_object_or_404(
            DataExportJob.objects.select_related("migration_export"),
            pk=job_id, makerspace_id=makerspace_id, fidelity="PORTABLE",
            migration_export__isnull=False,
        )
        audit.record(
            request.user, "tenant_migration.export_read", makerspace=job.makerspace,
            target=job, meta={"export_id": str(job.pk), "format_version": 1},
        )
        return Response(MigrationExportJobSerializer(job).data)


class MigrationExportDownloadUrlView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Issue the one-use PORTABLE archive download URL", request=None, responses={200: DataExportDownloadUrlSerializer, 400: CONFLICT, 404: NOT_FOUND, **AUTH_ERRORS})
    def post(self, request, makerspace_id, job_id):
        job = get_object_or_404(
            DataExportJob, pk=job_id, makerspace_id=makerspace_id,
            fidelity="PORTABLE", migration_export__isnull=False,
        )
        try:
            raw, expires_at = export_services.issue_download_token(job, request.user)
        except Exception as exc:
            return protocol_error(exc)
        url = request.build_absolute_uri(reverse("data-export-download", args=(job.pk, raw)))
        return Response(DataExportDownloadUrlSerializer({"url": url, "expires_at": expires_at}).data)
