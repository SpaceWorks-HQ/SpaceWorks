from rest_framework import serializers

from apps.integrations.notification_catalog import FEATURE_EVENTS
from apps.integrations.notification_enums import NonEmailNotificationChannel, NotificationDeliveryStatus
from apps.integrations.models_suppression import EmailSuppression


class DeliveryFilters(serializers.Serializer):
    channel = serializers.ChoiceField(choices=("email", *NonEmailNotificationChannel.values), required=False)
    status = serializers.ChoiceField(choices=NotificationDeliveryStatus.values, required=False)
    feature = serializers.ChoiceField(choices=tuple(FEATURE_EVENTS), required=False)
    event = serializers.CharField(max_length=64, required=False)
    destination = serializers.IntegerField(min_value=1, required=False)


class DeliverySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=("email", "channel"))
    channel = serializers.CharField()
    feature = serializers.CharField()
    event = serializers.CharField()
    destination_id = serializers.IntegerField(allow_null=True)
    destination_label = serializers.CharField()
    status = serializers.CharField()
    error = serializers.CharField()
    attempts = serializers.IntegerField()
    retry_generation = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField(allow_null=True)


class DeliveryPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = DeliverySerializer(many=True)


class RetrySerializer(serializers.Serializer):
    generation = serializers.IntegerField(min_value=0)


class DeliveryTestSerializer(serializers.Serializer):
    destination_id = serializers.IntegerField(min_value=1, required=False)


class DeliveryTestResultSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.IntegerField()
    status = serializers.CharField()


class SuppressionWriteSerializer(serializers.Serializer):
    address = serializers.EmailField(max_length=254, write_only=True)
    reason = serializers.ChoiceField(choices=EmailSuppression.Reason.choices)


class SuppressionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailSuppression
        fields = ("id", "address_hash", "reason", "created_at")
        read_only_fields = fields


class SuppressionPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = SuppressionSerializer(many=True)
