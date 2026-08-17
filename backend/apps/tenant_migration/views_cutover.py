from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.audit import services as audit
from apps.makerspaces.models import Makerspace

from . import cutover, pairing
from .deployment_keys import public_deployment_identity
from .models_import_job import TenantImportJob
from .models_protocol import MigrationPairing, TenantMigrationExportJob
from .serializers import (
    CutoverOutcomeSerializer,
    CutoverReceiptRequestSerializer,
    DeploymentIdentitySerializer,
    PairingCreateSerializer,
    PairingSerializer,
)
from .services_export_job import claim_completed_export
from .views_admission_export import MigrationAPIView
from .views_common import AUTH_ERRORS, CONFLICT, FIELD_ERRORS, NOT_FOUND, protocol_error

ARCHIVE_WARNING = (
    "Migration does not delete the source tenant. Cutover archives it through the "
    "two-key receipt flow, and archives are outside the purge guarantee."
)


class DeploymentIdentityView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Read this deployment's signing identity and target age recipient", responses={200: DeploymentIdentitySerializer, 409: CONFLICT, **AUTH_ERRORS})
    def get(self, request):
        identity = public_deployment_identity()
        identity["age_recipient"] = settings.TENANT_MIGRATION_AGE_RECIPIENT
        if not identity["age_recipient"]:
            return Response(
                {
                    "detail": "The target migration age recipient is not configured.",
                    "code": "age_recipient_not_configured",
                },
                status=409,
            )
        audit.record(
            request.user, "tenant_migration.deployment_identity_read",
            target=request.user, meta={"format_version": 1},
        )
        return Response(DeploymentIdentitySerializer(identity).data)


class MigrationPairingListCreateView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="List pinned migration pairings", responses={200: PairingSerializer(many=True), **AUTH_ERRORS})
    def get(self, request):
        rows = MigrationPairing.objects.all()[:20]
        audit.record(
            request.user, "tenant_migration.pairings_read", target=request.user,
            meta={"pairing_count": len(rows), "format_version": 1},
        )
        return Response(PairingSerializer(rows, many=True).data)

    @extend_schema(tags=["Tenant migration"], summary="Approve and pin source/target deployment identities", request=PairingCreateSerializer, responses={201: PairingSerializer, 400: FIELD_ERRORS, 409: CONFLICT, **AUTH_ERRORS})
    def post(self, request):
        serializer = PairingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = pairing.approve_pairing(actor=request.user, **serializer.validated_data)
        except Exception as exc:
            return protocol_error(exc)
        return Response(PairingSerializer(row).data, status=201)


class SourceQuiesceView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Reassert a completed export's source gate lease", request=None, responses={200: CutoverOutcomeSerializer, 404: NOT_FOUND, 409: CONFLICT, **AUTH_ERRORS})
    def post(self, request, makerspace_id, job_id):
        migration = get_object_or_404(
            TenantMigrationExportJob.objects.select_related("export_job__makerspace"),
            pk=job_id, export_job__makerspace_id=makerspace_id,
        )
        try:
            claim_completed_export(
                migration_export=migration,
                actor=request.user,
            )
        except Exception as exc:
            return protocol_error(exc)
        return Response({"message": ARCHIVE_WARNING})


class SourceArchiveView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Archive the quiesced source and issue its signed cutover receipt", request=None, responses={200: CutoverOutcomeSerializer, 404: NOT_FOUND, 409: CONFLICT, **AUTH_ERRORS})
    def post(self, request, makerspace_id, pairing_id):
        space = get_object_or_404(Makerspace, pk=makerspace_id)
        pair = get_object_or_404(MigrationPairing, pk=pairing_id)
        get_object_or_404(
            TenantMigrationExportJob.objects.select_related("export_job"),
            export_job__makerspace=space, archive_digest=pair.archive_digest,
        )
        try:
            receipt = cutover.retire_source(pairing=pair, makerspace=space, actor=request.user)
        except Exception as exc:
            return protocol_error(exc)
        return Response({"message": ARCHIVE_WARNING, "receipt": receipt})


class TargetActivateView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Activate an imported target with the source receipt", request=CutoverReceiptRequestSerializer, responses={200: CutoverOutcomeSerializer, 400: FIELD_ERRORS, 404: NOT_FOUND, 409: CONFLICT, **AUTH_ERRORS})
    def post(self, request, job_id, pairing_id):
        serializer = CutoverReceiptRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            receipt = cutover.activate_target(
                pairing=get_object_or_404(MigrationPairing, pk=pairing_id),
                import_job=get_object_or_404(TenantImportJob, pk=job_id),
                receipt_envelope=serializer.validated_data["receipt"], actor=request.user,
            )
        except Exception as exc:
            return protocol_error(exc)
        return Response({"message": ARCHIVE_WARNING, "receipt": receipt})


class TargetAbortView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Abort an importing target and issue its signed proof", request=None, responses={200: CutoverOutcomeSerializer, 404: NOT_FOUND, 409: CONFLICT, **AUTH_ERRORS})
    def post(self, request, job_id, pairing_id):
        try:
            receipt = cutover.abort_target(
                pairing=get_object_or_404(MigrationPairing, pk=pairing_id),
                import_job=get_object_or_404(TenantImportJob, pk=job_id), actor=request.user,
            )
        except Exception as exc:
            return protocol_error(exc)
        return Response({"message": ARCHIVE_WARNING, "receipt": receipt})


class SourceRecoverView(MigrationAPIView):
    @extend_schema(tags=["Tenant migration"], summary="Recover an archived source with the target abort receipt", request=CutoverReceiptRequestSerializer, responses={200: CutoverOutcomeSerializer, 400: FIELD_ERRORS, 404: NOT_FOUND, 409: CONFLICT, **AUTH_ERRORS})
    def post(self, request, makerspace_id, pairing_id):
        serializer = CutoverReceiptRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            receipt = cutover.reopen_source(
                pairing=get_object_or_404(MigrationPairing, pk=pairing_id),
                makerspace=get_object_or_404(Makerspace, pk=makerspace_id),
                receipt_envelope=serializer.validated_data["receipt"], actor=request.user,
            )
        except Exception as exc:
            return protocol_error(exc)
        return Response({"message": ARCHIVE_WARNING, "receipt": receipt})
