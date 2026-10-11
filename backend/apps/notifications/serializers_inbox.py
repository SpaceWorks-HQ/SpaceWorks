from rest_framework import serializers

from apps.integrations.notification_catalog import FEATURE_EVENTS
from apps.notifications.models_inbox import NotificationInboxRow
from apps.notifications.preferences import PERSONAL_CHANNELS


class InboxSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationInboxRow
        fields = ("id", "feature", "event", "title", "summary", "link", "read_at", "created_at")
        read_only_fields = fields


class InboxPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = InboxSerializer(many=True)


class CountSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class ReadAllSerializer(serializers.Serializer):
    updated = serializers.IntegerField()


class PreferenceWriteSerializer(serializers.Serializer):
    feature = serializers.ChoiceField(choices=tuple(FEATURE_EVENTS))
    channel = serializers.ChoiceField(choices=PERSONAL_CHANNELS)
    enabled = serializers.BooleanField()
    daily_digest = serializers.BooleanField(required=False)


class PreferenceCellSerializer(PreferenceWriteSerializer):
    available = serializers.BooleanField()
    mandatory_events = serializers.ListField(child=serializers.CharField())


class PreferenceResponseSerializer(serializers.Serializer):
    cells = PreferenceCellSerializer(many=True)


class UnsubscribeResultSerializer(serializers.Serializer):
    detail = serializers.CharField()
