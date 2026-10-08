"""Read-only makerspace custody status: Part A archive custody and Lane D tenant-exit custody."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.backup.models import MakerspaceArchiveCustodyState, MakerspaceTenantExitCustodyState
from apps.backup.module_gate import BACKUP_MODULE_KEY
from apps.backup.recipient_selection import effective_tenant_recipients
from apps.backup.views_common import AUTH_ERRORS, MODULE_OFF, NOT_FOUND
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace


class CustodyStateSerializer(serializers.Serializer):
    state = serializers.CharField()
    reason_code = serializers.CharField(allow_blank=True)
    entered_at = serializers.DateTimeField(allow_null=True)
    cleared_at = serializers.DateTimeField(allow_null=True)


class BackupCustodySerializer(serializers.Serializer):
    superadmin_access_enabled = serializers.BooleanField()
    verified_recipient_count = serializers.IntegerField()
    archive_custody = CustodyStateSerializer(allow_null=True)
    tenant_exit_custody = CustodyStateSerializer(allow_null=True)


def _state(model, makerspace):
    row = model.objects.filter(makerspace=makerspace).first()
    if row is None:
        return None
    return {
        "state": row.state,
        "reason_code": row.reason_code,
        "entered_at": row.entered_at,
        "cleared_at": row.cleared_at,
    }


class MakerspaceBackupCustodyView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Backup recipients"],
        summary="Get the makerspace's archive and tenant-exit custody status",
        responses={200: BackupCustodySerializer, 400: MODULE_OFF, 404: NOT_FOUND, **AUTH_ERRORS},
    )
    def get(self, request, makerspace_id):
        require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
        makerspace = require_module(
            get_object_or_404(Makerspace, pk=makerspace_id), BACKUP_MODULE_KEY
        )
        return Response(BackupCustodySerializer({
            "superadmin_access_enabled": makerspace.superadmin_access_enabled,
            "verified_recipient_count": len(effective_tenant_recipients(makerspace.pk)),
            "archive_custody": _state(MakerspaceArchiveCustodyState, makerspace),
            "tenant_exit_custody": _state(MakerspaceTenantExitCustodyState, makerspace),
        }).data)
