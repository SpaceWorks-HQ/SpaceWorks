from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.events.capacity import availability_label
from apps.events.models import Event, EventCollaborator
from apps.events.serializers_public import PublicEventRegistrationInputSerializer
from apps.inventory import public_image_storage
from apps.makerspaces.models import MakerspaceWaiver


class EventCollaboratorReplaceSerializer(serializers.Serializer):
    slugs = serializers.ListField(
        child=serializers.SlugField(),
        allow_empty=True,
    )


class EventCollaborationRespondSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class CollaborativeEventRegistrationInputSerializer(
    PublicEventRegistrationInputSerializer,
):
    host_waiver_id = serializers.IntegerField(
        min_value=1, required=False, allow_null=True,
    )
    host_waiver_version = serializers.CharField(
        max_length=64, required=False, allow_null=True,
    )
    # The affirmative act, required at the API boundary rather than assumed from the
    # presence of an id. A checkbox in one client is not evidence: without this field any
    # authenticated caller could echo back the visible id and version and the backend would
    # persist and audit an "acceptance" that nobody ever made -- which is worse than storing
    # nothing, because it manufactures evidence about a real person's agreement.
    host_waiver_accepted = serializers.BooleanField(required=False, default=False)


class HostWaiverSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    version = serializers.CharField(read_only=True)
    body = serializers.CharField(read_only=True)


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
    host_waiver = serializers.SerializerMethodField()

    @extend_schema_field(
        {"type": "string", "enum": ["Available", "Limited", "Full"]}
    )
    def get_availability(self, obj):
        return availability_label(obj)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        return public_image_storage.public_url(obj.image_key) or None

    @extend_schema_field(HostWaiverSerializer(allow_null=True))
    def get_host_waiver(self, obj):
        # Read from a context map built once by the view. Querying per row cost one query
        # per event -- and repeated identical queries whenever several events share a host --
        # on an unpaginated list. Falls back to a direct read so the serializer still works
        # when used on a single object without the context.
        waivers = self.context.get("active_host_waivers")
        if waivers is None:
            waiver = MakerspaceWaiver.objects.filter(
                makerspace=obj.makerspace, is_active=True,
            ).first()
        else:
            waiver = waivers.get(obj.makerspace_id)
        return HostWaiverSerializer(waiver).data if waiver else None
