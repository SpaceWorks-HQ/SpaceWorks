from rest_framework import serializers
from apps.devices.serializers_printers import StrictSerializer


class AckSerializer(StrictSerializer):
    lease_token = serializers.CharField(min_length=32, max_length=128)


class CommandLeaseSerializer(serializers.Serializer):
    command_id = serializers.UUIDField()
    kind = serializers.CharField()
    lease_token = serializers.CharField()
    lease_expires_at = serializers.DateTimeField()
    printer_job_id = serializers.UUIDField(required=False)
    external_job_id = serializers.CharField(required=False)
    service_request_id = serializers.IntegerField(required=False)
    label_command_id = serializers.UUIDField(required=False)
    qr_batch_id = serializers.IntegerField(required=False)
    item_count = serializers.IntegerField(required=False)


class LeaseResponseSerializer(serializers.Serializer):
    command = CommandLeaseSerializer(allow_null=True)


class CommandAckSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    acknowledged_at = serializers.DateTimeField(allow_null=True)
