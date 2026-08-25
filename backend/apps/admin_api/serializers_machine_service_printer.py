from decimal import Decimal

from rest_framework import serializers

from apps.machines.models import MachineConsumablePool, MachineUsageEntry


class PrinterPoolSerializer(serializers.ModelSerializer):
    machine_id = serializers.IntegerField(read_only=True, allow_null=True)
    machine_type_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = MachineConsumablePool
        fields = ("id", "machine_id", "machine_type_id", "material", "color", "color_hex", "brand", "lot_code", "unit", "initial_grams", "remaining_grams", "low_threshold_grams", "is_active", "is_public", "opened_at", "created_at", "updated_at")
        read_only_fields = ("id", "remaining_grams", "is_active", "created_at", "updated_at")


class PrinterPoolCreateSerializer(serializers.Serializer):
    machine_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    machine_type_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    is_public = serializers.BooleanField(required=False, default=True)
    material = serializers.CharField(max_length=100)
    color = serializers.CharField(max_length=100, required=False, allow_blank=True)
    color_hex = serializers.CharField(max_length=7, required=False, allow_blank=True)
    brand = serializers.CharField(max_length=100, required=False, allow_blank=True)
    lot_code = serializers.CharField(max_length=100, required=False, allow_blank=True)
    unit = serializers.ChoiceField(choices=("grams", "milliliters", "millimeters", "count"), required=False, default="grams")
    quantity = serializers.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=Decimal("0"))
    initial_grams = serializers.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=Decimal("0"))
    low_threshold_grams = serializers.DecimalField(required=False, allow_null=True, max_digits=12, decimal_places=2, min_value=Decimal("0"))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("machine_id") is not None and attrs.get("machine_type_id") is not None:
            raise serializers.ValidationError({
                "machine_type_id": "Choose either machine_id or machine_type_id, not both."
            })
        if attrs.get("quantity") is None and attrs.get("initial_grams") is None:
            raise serializers.ValidationError({"quantity": "quantity or initial_grams is required."})
        if attrs.get("quantity") is not None and attrs.get("initial_grams") is not None:
            raise serializers.ValidationError("Provide only quantity or initial_grams.")
        return attrs


class PrinterPoolVisibilitySerializer(serializers.Serializer):
    is_public = serializers.BooleanField()


class PrinterPoolCorrectionSerializer(serializers.Serializer):
    quantity_delta = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)


class TypedManualUsageSerializer(serializers.Serializer):
    machine_id = serializers.IntegerField(min_value=1)
    consumable_pool_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    service_request_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    duration_minutes = serializers.IntegerField(min_value=0)
    outcome = serializers.ChoiceField(choices=("success", "failed"))
    percent_complete = serializers.IntegerField(min_value=0, max_value=100, default=100)
    reason = serializers.CharField(required=False, allow_blank=True)
    grams = serializers.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=Decimal("0"), default=Decimal("0"))
    quantity = serializers.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=Decimal("0"))
    metering_unit = serializers.ChoiceField(choices=("minutes", "weight", "volume", "length", "count"), required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class TypedManualUsageResponseSerializer(serializers.ModelSerializer):
    machine_id = serializers.IntegerField(read_only=True)
    consumable_pool_id = serializers.IntegerField(read_only=True, allow_null=True)
    service_request_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = MachineUsageEntry
        fields = ("id", "machine_id", "consumable_pool_id", "service_request_id", "duration_minutes", "outcome", "percent_complete", "reason", "consumed_grams", "metering_unit", "consumed_quantity", "hours", "note", "created_at")
        read_only_fields = fields
