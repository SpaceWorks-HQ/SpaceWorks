from rest_framework import serializers

from apps.events.serializers_public import EventOrganizerSummarySerializer


class EventOrganizerReplaceSerializer(serializers.Serializer):
    organization_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        max_length=50,
        allow_empty=True,
    )


class EventOrganizerListSerializer(serializers.Serializer):
    organizers = EventOrganizerSummarySerializer(many=True, read_only=True)
