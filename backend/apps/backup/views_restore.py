from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.audit import services as audit
from apps.backup.models import PlatformBackupSettings, RestoreOperation
from apps.backup.restore_services import decide_restore, request_restore
from apps.backup.serializers import (
    PlatformBackupSettingsSerializer,
    RestoreCreateSerializer,
    RestoreDecisionSerializer,
    RestoreOperationSerializer,
)
from apps.backup.views_common import AUTH_ERRORS, NOT_FOUND, VALIDATION_ERROR


class PlatformBackupSettingsView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=["Backup"], summary="Get deployment backup settings", responses={200: PlatformBackupSettingsSerializer, **AUTH_ERRORS})
    def get(self, request):
        return Response(PlatformBackupSettingsSerializer(PlatformBackupSettings.load()).data)

    @extend_schema(tags=["Backup"], summary="Update deployment backup settings", request=PlatformBackupSettingsSerializer, responses={200: PlatformBackupSettingsSerializer, 400: VALIDATION_ERROR, **AUTH_ERRORS})
    def patch(self, request):
        row = PlatformBackupSettings.load()
        serializer = PlatformBackupSettingsSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = serializer.save()
        audit.record(request.user, "backup.settings_updated", target=row, meta=serializer.validated_data)
        return Response(PlatformBackupSettingsSerializer(row).data)


class RestoreOperationListCreateView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=["Backup"], summary="List deployment restore operations", responses={200: RestoreOperationSerializer(many=True), **AUTH_ERRORS})
    def get(self, request):
        return Response(RestoreOperationSerializer(RestoreOperation.objects.all()[:20], many=True).data)

    @extend_schema(tags=["Backup"], summary="Record restore intent for the privileged host supervisor", request=RestoreCreateSerializer, responses={202: RestoreOperationSerializer, 400: VALIDATION_ERROR, **AUTH_ERRORS})
    def post(self, request):
        serializer = RestoreCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restore = request_restore(request.user, **serializer.validated_data)
        return Response(RestoreOperationSerializer(restore).data, status=status.HTTP_202_ACCEPTED)


class RestoreOperationView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=["Backup"], summary="Get restore stage, diff, and decision deadline", responses={200: RestoreOperationSerializer, 404: NOT_FOUND, **AUTH_ERRORS})
    def get(self, request, restore_id):
        return Response(RestoreOperationSerializer(get_object_or_404(RestoreOperation, pk=restore_id)).data)


class RestoreDecisionView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=["Backup"], summary="Decide a quiesced in-place restore", request=RestoreDecisionSerializer, responses={200: RestoreOperationSerializer, 400: VALIDATION_ERROR, 404: NOT_FOUND, **AUTH_ERRORS})
    def post(self, request, restore_id):
        serializer = RestoreDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        restore = decide_restore(request.user, restore_id, serializer.validated_data["decision"])
        return Response(RestoreOperationSerializer(restore).data)
