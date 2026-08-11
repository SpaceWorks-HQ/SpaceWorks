from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.events.capacity import availability_label
from apps.events.models import Event, EventCollaborator
from apps.inventory import public_image_storage


class EventCollaboratorReplaceSerializer(serializers.Serializer):
    slugs = serializers.ListField(
        child=serializers.SlugField(),
        allow_empty=True,
    )


class EventCollaborationRespondSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class EventCollaboratorSerializer(serializers.ModelSerializer):
    event_id = serializers.IntegerField(read_only=True)
    makerspace_id = serializers.IntegerField(read_only=True)
    makerspace_name = serializers.CharField(source="makerspace.name", read_only=True)
    makerspace_slug = serializers.SlugField(source="makerspace.slug", read_only=True)
    invited_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    responded_by_id = serializers.IntegerField(allow_null=True, read_only=True)

    class Meta:
        model = EventCollaborator
        fields = (
            "id", "event_id", "makerspace_id", "makerspace_name",
            "makerspace_slug", "status", "invited_by_id", "responded_by_id",
            "created_at", "responded_at",
        )
        read_only_fields = fields


class EventCollaborationInboxSerializer(serializers.ModelSerializer):
    event_id = serializers.IntegerField(read_only=True)
    event_title = serializers.CharField(source="event.title", read_only=True)
    starts_at = serializers.DateTimeField(source="event.starts_at", read_only=True)
    ends_at = serializers.DateTimeField(source="event.ends_at", read_only=True)
    host_name = serializers.CharField(source="event.makerspace.name", read_only=True)
    host_slug = serializers.SlugField(source="event.makerspace.slug", read_only=True)

    class Meta:
        model = EventCollaborator
        fields = (
            "id", "event_id", "event_title", "starts_at", "ends_at",
            "host_name", "host_slug", "status", "created_at", "responded_at",
        )
        read_only_fields = fields


class CollaborativeEventSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    location = serializers.CharField(read_only=True)
    location_kind = serializers.ChoiceField(
        choices=Event.LocationKind.choices,
        read_only=True,
    )
    custom_form = serializers.JSONField(allow_null=True, read_only=True)
    capacity = serializers.IntegerField(min_value=0, read_only=True)
    availability = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    host_name = serializers.CharField(source="makerspace.name", read_only=True)
    host_slug = serializers.SlugField(source="makerspace.slug", read_only=True)

    @extend_schema_field(
        {"type": "string", "enum": ["Available", "Limited", "Full"]}
    )
    def get_availability(self, obj):
        return availability_label(obj)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        return public_image_storage.public_url(obj.image_key) or None
