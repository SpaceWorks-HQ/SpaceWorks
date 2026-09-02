from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.events.capacity import availability_label
from apps.events.models import Event, EventRegistration
from apps.forms_schema.serializers import CustomFormSubmissionMixin
from apps.inventory import public_image_storage


PUBLIC_EVENT_FIELDS = (
    'public_token',
    'title',
    'description',
    'starts_at',
    'ends_at',
    'location',
    'location_kind',
    'custom_form',
    'capacity',
    'availability',
    'image_url',
    'status',
    'organizers',
)


class EventOrganizerSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(source='organization.id', read_only=True)
    slug = serializers.SlugField(source='organization.slug', read_only=True)
    name = serializers.CharField(source='organization.name', read_only=True)


class PublicEventSerializer(serializers.Serializer):
    public_token = serializers.UUIDField(read_only=True)
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
    status = serializers.ChoiceField(
        choices=[Event.Status.PUBLISHED],
        read_only=True,
    )
    organizers = EventOrganizerSummarySerializer(many=True, read_only=True)

    @extend_schema_field(
        {
            'type': 'string',
            'enum': ['Available', 'Limited', 'Full'],
        }
    )
    def get_availability(self, obj):
        return availability_label(obj)

    # The object key itself stays server-side; the public payload carries only the
    # resolved URL, exactly as PublicMachineSerializer does.
    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        return public_image_storage.public_url(obj.image_key) or None


class PublicEventRegistrationInputSerializer(
    CustomFormSubmissionMixin,
    serializers.Serializer,
):
    def custom_form_schema(self):
        return self.context['event'].custom_form


class PublicEventRegistrationResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(
            EventRegistration.Status.REGISTERED,
            EventRegistration.Status.WAITLISTED,
        ),
        read_only=True,
    )
