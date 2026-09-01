from decimal import Decimal

from rest_framework import serializers

from apps.machines.serializers_machines import MachineSerializer


class MachineListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = MachineSerializer(many=True)


class SetStatusSerializer(serializers.Serializer):
    status = serializers.CharField(max_length=20)


class MachinePublicitySerializer(serializers.Serializer):
    is_public = serializers.BooleanField()


class LogUsageSerializer(serializers.Serializer):
    hours = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
    )
    note = serializers.CharField(max_length=255, allow_blank=True, required=False)


class AssignOperatorSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    access_level = serializers.CharField(max_length=16)


class LogErrorSerializer(serializers.Serializer):
    severity = serializers.CharField(max_length=16)
    message = serializers.CharField()


class DocumentPresignSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)


class DocumentFinalizeSerializer(serializers.Serializer):
    object_key = serializers.CharField(max_length=255)
    doc_type = serializers.CharField(max_length=16)
    original_filename = serializers.CharField(max_length=255)
