"""Strict printer protocol: measurements only; no device-controlled money fields."""
from decimal import Decimal

from rest_framework import serializers

from apps.devices.models import PrinterDeviceBinding, PrinterJob, PrinterJobConsumption


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("An object is required.")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown field." for key in sorted(unknown)})
        return super().to_internal_value(data)


class BindingCreateSerializer(StrictSerializer):
    device_id = serializers.UUIDField()
    machine_id = serializers.IntegerField(min_value=1)
    enabled = serializers.BooleanField(default=True)
    auto_apply_terminal = serializers.BooleanField(default=False)


class BindingUpdateSerializer(StrictSerializer):
    enabled = serializers.BooleanField(required=False)
    auto_apply_terminal = serializers.BooleanField(required=False)


class BindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrinterDeviceBinding
        fields = ["id", "makerspace", "device", "machine", "enabled", "auto_apply_terminal", "created_at", "updated_at"]
        read_only_fields = fields


class JobCreateSerializer(StrictSerializer):
    binding_id = serializers.UUIDField()
    service_request_id = serializers.IntegerField(min_value=1)
    external_job_id = serializers.CharField(max_length=120)


class ConsumptionSerializer(StrictSerializer):
    machine_consumable_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class ResultSerializer(StrictSerializer):
    operation_id = serializers.UUIDField()
    external_job_id = serializers.CharField(max_length=120)
    outcome = serializers.ChoiceField(choices=["completed", "failed"])
    actual_minutes = serializers.IntegerField(min_value=0, max_value=2147483647)
    consumptions = ConsumptionSerializer(many=True, allow_empty=True)
    failure_reason = serializers.CharField(max_length=1000, required=False, default="", allow_blank=True)
    percent_complete = serializers.IntegerField(min_value=0, max_value=100, required=False, allow_null=True, default=None)
    actual_grams = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True, default=None)
    actual_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True, default=None)

    def validate(self, attrs):
        if attrs["outcome"] == "failed" and (not attrs["failure_reason"].strip() or attrs["percent_complete"] is None):
            raise serializers.ValidationError("Failure requires a reason and percent_complete.")
        if attrs["outcome"] == "completed" and (attrs["failure_reason"] or attrs["percent_complete"] is not None):
            raise serializers.ValidationError("Completed reports cannot contain failure fields.")
        if attrs["actual_grams"] is not None and attrs["actual_quantity"] is not None:
            raise serializers.ValidationError("Supply actual_grams or actual_quantity, not both.")
        ids = [row["machine_consumable_id"] for row in attrs["consumptions"]]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Each consumable may appear once.")
        return attrs


class TelemetrySerializer(StrictSerializer):
    external_job_id = serializers.CharField(max_length=120)
    telemetry_state = serializers.ChoiceField(choices=["idle", "running", "paused"])
    progress_percent = serializers.IntegerField(min_value=0, max_value=100)


class JobConsumptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrinterJobConsumption
        fields = ["machine_consumable", "machine_consumable_id_snapshot", "quantity"]


class JobSerializer(serializers.ModelSerializer):
    consumptions = JobConsumptionSerializer(many=True, read_only=True)

    class Meta:
        model = PrinterJob
        fields = ["id", "command", "makerspace", "device", "machine", "service_request",
                  "machine_name", "service_request_name", "external_job_id", "state",
                  "telemetry_state", "progress_percent", "telemetry_at", "terminal_operation_id",
                  "outcome", "actual_minutes", "failure_reason", "percent_complete", "actual_grams",
                  "actual_quantity", "reported_at", "applied_at", "processed_by", "created_at", "consumptions"]
        read_only_fields = fields
