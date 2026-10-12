"""Makerspace-wide, machine-scoped read projection for the dashboard drill-down."""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.machines import role_scope
from apps.makerspaces.guards import require_module
from apps.makerspaces.servability import servable_queryset
from apps.maintenance.models import MaintenanceSchedule
from apps.openapi_errors import errors


class OverdueScheduleSerializer(serializers.ModelSerializer):
    machine_id = serializers.IntegerField(read_only=True)
    machine_name = serializers.CharField(source="machine.name", read_only=True)

    class Meta:
        model = MaintenanceSchedule
        fields = ("id", "machine_id", "machine_name", "description", "next_due")
        read_only_fields = fields


@extend_schema(tags=["Admin maintenance"], summary="List overdue maintenance in my machine scope",
               request=None, responses={200: OverdueScheduleSerializer(many=True), **errors(400, 401, 403, 404)})
class OverdueMaintenanceListView(generics.ListAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = OverdueScheduleSerializer

    def get_queryset(self):
        actor = self.request.user
        action = rbac.Action.MANAGE_MACHINES
        space = get_object_or_404(rbac.scope_by_action(actor, action, servable_queryset(), field="id"),
                                 pk=self.kwargs["makerspace_id"])
        require_module(space, "maintenance")
        require_module(space, "machines")
        query = rbac.scope_by_action(actor, action, MaintenanceSchedule.objects.all(),
                                     field="machine__makerspace_id")
        scope = role_scope.manage_scope_for(actor, space.pk)
        from .meters import due_queryset
        query = due_queryset(query.filter(machine__makerspace=space, is_active=True), timezone.localdate())
        return query.filter(
            role_scope.scope_q_for(scope, machine_id_paths=("machine_id",),
                                   type_id_paths=("machine__machine_type_id",)),
        ).select_related("machine").order_by("next_due", "pk")
