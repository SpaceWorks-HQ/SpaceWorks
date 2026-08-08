from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.maintenance.models import (
    MaintenanceLog,
    MaintenanceLogDocument,
    MaintenanceSchedule,
)


class StrictFieldsSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        unexpected = set(data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(
                {field: "Unexpected field." for field in sorted(unexpected)}
            )
        return super().to_internal_value(data)


class MaintenanceScheduleWriteSerializer(StrictFieldsSerializer):
    description = serializers.CharField()
    interval_days = serializers.IntegerField(min_value=1)
    next_due = serializers.DateField()


class MaintenanceScheduleSerializer(serializers.ModelSerializer):
    machine_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    overdue = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceSchedule
        fields = (
            "id", "machine_id", "description", "interval_days", "next_due",
            "is_active", "created_by_id", "created_at", "updated_at", "overdue",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def get_overdue(self, obj):
        return bool(obj.is_active and obj.next_due < self.context["today"])


class MaintenanceLogDocumentSerializer(serializers.ModelSerializer):
    log_id = serializers.IntegerField(read_only=True)
    uploaded_by_id = serializers.IntegerField(allow_null=True, read_only=True)

    class Meta:
        model = MaintenanceLogDocument
        fields = (
            "id", "log_id", "object_key", "size_bytes",
            "uploaded_by_id", "created_at",
        )
        read_only_fields = fields


class MaintenanceLogSerializer(serializers.ModelSerializer):
    machine_id = serializers.IntegerField(read_only=True)
    performed_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    documents = MaintenanceLogDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = MaintenanceLog
        fields = (
            "id", "machine_id", "performed_by_id", "performed_at", "summary",
            "cost", "parts_note", "created_at", "documents",
        )
        read_only_fields = fields


class MaintenanceLogWriteSerializer(StrictFieldsSerializer):
    summary = serializers.CharField()
    performed_at = serializers.DateTimeField(required=False)
    cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0,
        allow_null=True, required=False,
    )
    parts_note = serializers.CharField(allow_blank=True, default="", required=False)
    set_idle = serializers.BooleanField(default=False, required=False)
    schedule_id = serializers.IntegerField(min_value=1, required=False, write_only=True)


class MaintenanceDocumentPresignSerializer(StrictFieldsSerializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)


class MaintenanceDocumentUploadSerializer(serializers.Serializer):
    url = serializers.URLField()
    method = serializers.CharField(required=False)
    fields = serializers.DictField(required=False)
    headers = serializers.DictField(required=False)


class MaintenanceDocumentPresignResponseSerializer(serializers.Serializer):
    object_key = serializers.CharField()
    upload = MaintenanceDocumentUploadSerializer()


class MaintenanceDocumentFinalizeSerializer(StrictFieldsSerializer):
    object_key = serializers.CharField(max_length=500)


class MaintenanceDocumentUrlSerializer(serializers.Serializer):
    url = serializers.URLField()


class EmptyActionSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if data:
            raise serializers.ValidationError(
                {field: "Unexpected field." for field in data}
            )
        return value


class MaintenanceScheduleListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = MaintenanceScheduleSerializer(many=True)


class MaintenanceLogListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = MaintenanceLogSerializer(many=True)
