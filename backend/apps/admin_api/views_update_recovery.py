from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.admin_api.serializers_platform_updates import (
    PlatformUpdateSettingsSerializer, UpdateRollbackSerializer,
)
from apps.admin_api.views_platform_updates import UPDATE_REFUSAL_RESPONSE, _require_updates_module
from apps.backup.serializers import RestoreOperationSerializer
from apps.openapi_errors import errors
from apps.updates.recovery import recover_stuck_update
from apps.updates.errors import UpdateRefused
from apps.updates.rollback import request_update_rollback


class PlatformUpdateRecoverView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(
        tags=["Platform"], summary="Recover a timed-out update after proving the host lock is free",
        request=None, responses={200: PlatformUpdateSettingsSerializer, **errors(401, 403), 400: UPDATE_REFUSAL_RESPONSE},
        description="Idempotent once recovered. Refuses module_disabled, update_not_stuck and host_operation_active.",
    )
    def post(self, request):
        _require_updates_module()
        row = recover_stuck_update(request.user)
        return Response(PlatformUpdateSettingsSerializer(row).data)


class PlatformUpdateRollbackView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(
        tags=["Platform"], summary="Queue confirmed rollback to the recorded pre-update restore point",
        request=UpdateRollbackSerializer,
        responses={202: RestoreOperationSerializer, **errors(401, 403), 400: UPDATE_REFUSAL_RESPONSE},
        description=(
            "The privileged host uses the existing restore supervisor and previous immutable images. "
            "Requires archive_id, confirm_version and confirm_data_loss. Refusals carry a reason: "
            "module_disabled, invalid_confirmation, no_snapshot, no_previous_version, snapshot_unavailable, snapshot_unverified, "
            "snapshot_unsupported, confirmation_mismatch, update_busy, rollback_completed or restore_refused. "
            "The existing quiesced restore diff requires a second proceed/reset/abort decision."
        ),
    )
    def post(self, request):
        _require_updates_module()
        serializer = UpdateRollbackSerializer(data=request.data)
        if not serializer.is_valid():
            raise UpdateRefused("invalid_confirmation", "Supply archive_id, confirm_version and confirm_data_loss with valid types.")
        restore = request_update_rollback(request.user, **serializer.validated_data)
        return Response(RestoreOperationSerializer(restore).data, status=202)
