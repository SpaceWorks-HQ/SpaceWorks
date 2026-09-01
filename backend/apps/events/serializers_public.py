from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from django.utils import timezone

from apps.events.capacity import (
    availability_label,
    effective_registration_cutoff,
    registration_is_open,
)
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
    'registration_requires_approval',
    'effective_registration_cutoff_at',
    'registration_open',
    'image_url',
    'status',
    'organizers',
    'series',
)


class EventOrganizerSummarySerializer(serializers.Serializer):
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
    registration_requires_approval = serializers.BooleanField(read_only=True)
    effective_registration_cutoff_at = serializers.SerializerMethodField()
    registration_open = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    status = serializers.ChoiceField(
        choices=[Event.Status.PUBLISHED],
        read_only=True,
    )
    organizers = EventOrganizerSummarySerializer(many=True, read_only=True)
    series = serializers.SerializerMethodField()

    @extend_schema_field(
        {
            'type': 'string',
            'enum': ['Available', 'Limited', 'Full'],
        }
    )
    def get_availability(self, obj):
        return availability_label(obj)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_effective_registration_cutoff_at(self, obj):
        return effective_registration_cutoff(obj)

    @extend_schema_field(serializers.BooleanField())
    def get_registration_open(self, obj):
        return registration_is_open(obj, timezone.now())

    # The object key itself stays server-side; the public payload carries only the
    # resolved URL, exactly as PublicMachineSerializer does.
    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        key = obj.image_key
        if obj.series_id and "image_key" not in (obj.series_override_fields or []):
            key = obj.series.image_key
        return public_image_storage.public_url(key) or None

    @extend_schema_field({
        'type': 'object', 'nullable': True,
        'properties': {
            'public_token': {'type': 'string', 'format': 'uuid'},
            'title': {'type': 'string'},
        },
    })
    def get_series(self, obj):
        if not obj.series_id:
            return None
        return {'public_token': obj.series.public_token, 'title': obj.series.title}


class PublicEventRegistrationInputSerializer(
    CustomFormSubmissionMixin,
    serializers.Serializer,
):
    def custom_form_schema(self):
        return self.context['event'].custom_form


class PublicEventRegistrationResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(
            EventRegistration.Status.PENDING_APPROVAL,
            EventRegistration.Status.REGISTERED,
            EventRegistration.Status.WAITLISTED,
        ),
        read_only=True,
    )
