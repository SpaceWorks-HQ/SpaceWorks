from drf_spectacular.utils import extend_schema
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backup.models import DeploymentRecoveryState
from apps.backup.recovery import acknowledge_quarantine, can_read_recovery_state
from apps.backup.serializers import RecoveryAcknowledgeSerializer, RecoveryStateSerializer
from apps.backup.views_common import AUTH_ERRORS, VALIDATION_ERROR


class IsSuperadminOrRecoveryPrincipal(BasePermission):
    def has_permission(self, request, view):
        return can_read_recovery_state(getattr(request, "user", None))


class RecoveryStateView(APIView):
    permission_classes = [IsSuperadminOrRecoveryPrincipal]

    @extend_schema(tags=["Backup recovery"], summary="Get deployment quarantine and residual-risk state", responses={200: RecoveryStateSerializer, **AUTH_ERRORS})
    def get(self, request):
        return Response(RecoveryStateSerializer(DeploymentRecoveryState.load()).data)

    @extend_schema(tags=["Backup recovery"], summary="Acknowledge residual risk and lift quarantine", request=RecoveryAcknowledgeSerializer, responses={200: RecoveryStateSerializer, 400: VALIDATION_ERROR, **AUTH_ERRORS})
    def post(self, request):
        serializer = RecoveryAcknowledgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        state = acknowledge_quarantine(request.user, serializer.validated_data["acknowledgement"])
        return Response(RecoveryStateSerializer(state).data)
