"""Numeric policy is space-manager configuration, not broad machine authority."""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.audit.services import record
from apps.machines.models import MachineType, MakerspaceMachineTypePolicy
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.openapi_errors import errors


class MachineTypePolicySerializer(serializers.ModelSerializer):
    cert_reminder_days = serializers.IntegerField(min_value=0, max_value=365, allow_null=True, required=False)
    reminder_lead_days = serializers.IntegerField(min_value=0, max_value=365, allow_null=True, required=False)
    grace_days = serializers.IntegerField(min_value=0, max_value=365, allow_null=True, required=False)

    class Meta:
        model = MakerspaceMachineTypePolicy
        fields = ["cert_reminder_days", "reminder_lead_days", "grace_days"]


class MachineTypePolicyView(APIView):
    permission_classes = [IsActiveStaff]

    def resolve(self, actor, makerspace_id, machine_type_id):
        makerspace = get_object_or_404(rbac.scope_by_makerspace(
            actor, Makerspace.objects.all(), makerspace_field="pk",
        ), pk=makerspace_id)
        require_module(makerspace, "machines")
        if not rbac.is_space_manager_identity(actor, makerspace.pk):
            raise PermissionDenied()
        machine_type = get_object_or_404(MachineType.objects.filter(
            Q(makerspace__isnull=True) | Q(pk__in=rbac.scope_by_makerspace(
                actor, MachineType.objects.all(),
            ).filter(makerspace=makerspace).values("pk")),
        ), pk=machine_type_id)
        return makerspace, machine_type

    @extend_schema(tags=["Admin machines"], summary="Read machine-type reminder policy",
                   request=None, responses={200: MachineTypePolicySerializer, **errors(400, 401, 403, 404)})
    def get(self, request, makerspace_id, machine_type_id):
        makerspace, machine_type = self.resolve(request.user, makerspace_id, machine_type_id)
        row = rbac.scope_by_makerspace(request.user, MakerspaceMachineTypePolicy.objects.all()).filter(
            makerspace=makerspace, machine_type=machine_type,
        ).first() or MakerspaceMachineTypePolicy(makerspace=makerspace, machine_type=machine_type)
        return Response(MachineTypePolicySerializer(row).data)

    @extend_schema(tags=["Admin machines"], summary="Set machine-type reminder policy",
                   request=MachineTypePolicySerializer,
                   responses={200: MachineTypePolicySerializer, **errors(400, 401, 403, 404, 423)})
    @transaction.atomic
    def put(self, request, makerspace_id, machine_type_id):
        makerspace, machine_type = self.resolve(request.user, makerspace_id, machine_type_id)
        serializer = MachineTypePolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row, _ = rbac.scope_by_makerspace(request.user, MakerspaceMachineTypePolicy.objects.all()).update_or_create(
            makerspace=makerspace, machine_type=machine_type, defaults=serializer.validated_data,
        )
        record(request.user, "machine_type.policy_updated", makerspace=makerspace,
               target=row, meta={"fields": sorted(serializer.validated_data)})
        return Response(MachineTypePolicySerializer(row).data)
