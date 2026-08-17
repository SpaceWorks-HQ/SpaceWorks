from datetime import timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.audit import services as audit

from .models_import_job import TenantImportJob
from .serializers import (
    ClosureIdentitySerializer,
    ImportCreateSerializer,
    ImportDecisionListSerializer,
    ImportJobSerializer,
    ImportRunSerializer,
    VerificationReportSerializer,
)
from .services_import_job import (
    claim_import_job,
    create_import_job,
    submit_identity_decisions,
)
from .tasks import run_import_job_task
from .views_admission_export import MigrationAPIView
from .views_common import AUTH_ERRORS, CONFLICT, FIELD_ERRORS, NOT_FOUND, protocol_error


def _job(job_id):
    return get_object_or_404(TenantImportJob, pk=job_id)


class TenantImportListCreateView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="List tenant import jobs", responses={200: ImportJobSerializer(many=True), **AUTH_ERRORS})
    def get(self, request):
        rows = TenantImportJob.objects.all()[:20]
        audit.record(
            request.user, "tenant_migration.imports_read", target=request.user,
            meta={"import_count": len(rows), "format_version": 1},
        )
        return Response(ImportJobSerializer(rows, many=True).data)

    @extend_schema(tags=["Tenant migration"], summary="Create an import job from an age-encrypted archive upload", request=ImportCreateSerializer, responses={201: ImportJobSerializer, 400: FIELD_ERRORS, 409: CONFLICT, **AUTH_ERRORS})
    def post(self, request):
        serializer = ImportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job = create_import_job(
                actor=request.user,
                expires_at=timezone.now() + timedelta(
                    seconds=settings.DATA_EXPORT_RETENTION_SECONDS
                ),
                **serializer.validated_data,
            )
        except Exception as exc:
            return protocol_error(exc)
        return Response(ImportJobSerializer(job).data, status=status.HTTP_201_CREATED)


class TenantImportDetailView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Read a tenant import job", responses={200: ImportJobSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request, job_id):
        job = _job(job_id)
        audit.record(
            request.user, "tenant_migration.import_read", target=job,
            meta={"import_id": str(job.pk), "format_version": 1},
        )
        return Response(ImportJobSerializer(job).data)


class TenantImportIdentityDecisionsView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Read the exact archived identity decision list", responses={200: ClosureIdentitySerializer(many=True), 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request, job_id):
        from .archive_stream import PortableArchive
        from .import_staging import decrypted_archive

        job = _job(job_id)
        try:
            with decrypted_archive(job.archive_path) as (root, _carried):
                rows = list(PortableArchive(root).rows("accounts.User"))
        except Exception as exc:
            return protocol_error(exc)
        audit.record(
            request.user, "tenant_migration.identity_decisions_read", target=job,
            meta={
                "import_id": str(job.pk), "identity_count": len(rows),
                "format_version": 1,
            },
        )
        return Response(ClosureIdentitySerializer(rows, many=True).data)

    @extend_schema(tags=["Tenant migration"], summary="Submit all per-person import identity decisions", request=ImportDecisionListSerializer, responses={200: ImportJobSerializer, 400: FIELD_ERRORS, 409: CONFLICT, 404: NOT_FOUND, **AUTH_ERRORS})
    def post(self, request, job_id):
        serializer = ImportDecisionListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job = submit_identity_decisions(
                actor=request.user, job=_job(job_id),
                decisions=serializer.validated_data["decisions"],
            )
        except Exception as exc:
            return protocol_error(exc)
        return Response(ImportJobSerializer(job).data)


class TenantImportRunView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Run an identity-decided tenant import", request=ImportRunSerializer, responses={202: ImportJobSerializer, 400: FIELD_ERRORS, 409: CONFLICT, 404: NOT_FOUND, 503: OpenApiResponse(description="Import worker unavailable."), **AUTH_ERRORS})
    def post(self, request, job_id):
        serializer = ImportRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job = claim_import_job(actor=request.user, job=_job(job_id))
        except Exception as exc:
            return protocol_error(exc)
        try:
            run_import_job_task.delay(
                str(job.pk), request.user.pk, serializer.validated_data["target_identity"]
            )
        except Exception:
            TenantImportJob.objects.filter(pk=job.pk).update(
                status=TenantImportJob.Status.FAILED,
                failure_code="worker_unavailable",
                failure_detail="The tenant import worker is unavailable.",
                terminal_at=timezone.now(),
            )
            return Response(
                {"detail": "The tenant import worker is unavailable.", "code": "worker_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(ImportJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class TenantImportVerificationView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Read the import verification report", responses={200: VerificationReportSerializer, 404: NOT_FOUND, 409: CONFLICT, **AUTH_ERRORS})
    def get(self, request, job_id):
        job = _job(job_id)
        if not job.verification_report:
            return Response(
                {"detail": "The verification report is not available.", "code": "report_unavailable"},
                status=status.HTTP_409_CONFLICT,
            )
        audit.record(
            request.user, "tenant_migration.verification_read", target=job,
            meta={
                "import_id": str(job.pk),
                "model_count": len(job.verification_report.get("imported", {})),
                "format_version": job.verification_report.get("format_version", 0),
            },
        )
        return Response(VerificationReportSerializer(job.verification_report).data)
