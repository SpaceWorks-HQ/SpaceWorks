from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from django.db.models import Sum
from apps.accounts import rbac
from .models import MachineUsageEntry

from .serializers_public_machines import PublicMachineSerializer
from .public_detail import queue_estimate, training


class PublicQueueEstimateSerializer(serializers.Serializer):
    length = serializers.IntegerField(min_value=0)
    eta_minutes = serializers.IntegerField(min_value=0, allow_null=True)


class PublicMachineDetailSerializer(PublicMachineSerializer):
    machine_type = serializers.SerializerMethodField()
    id = serializers.IntegerField(read_only=True)

    @extend_schema_field({"type": "string", "format": "decimal"})
    def get_usage_hours(self, machine):
        total = rbac.scope_verified_tenant(MachineUsageEntry.objects.all(), machine.makerspace,
            field="machine__makerspace_id").filter(machine=machine).aggregate(total=Sum("hours"))["total"] or 0
        return f"{total:.2f}"

    @extend_schema_field({"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "icon": {"type": "string"}}})
    def get_machine_type(self, machine):
        return {"id": machine.machine_type_id, "name": machine.machine_type.name, "icon": machine.machine_type.icon}
    status_since = serializers.DateTimeField(read_only=True)
    training_required = serializers.SerializerMethodField()
    queue = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_training_required(self, machine):
        return training(machine)

    @extend_schema_field(PublicQueueEstimateSerializer(allow_null=True))
    def get_queue(self, machine):
        return queue_estimate(machine)
