from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.events.models import Event, EventRegistration
from apps.events.capacity import effective_registration_cutoff, registration_is_open
from apps.forms_schema.serializers import CustomFormSchemaField
from apps.inventory import public_image_storage
from apps.makerspaces.platform import feature_enabled
from apps.admin_api.serializers_payment_summary import PaymentSummaryMixin
from apps.events.serializers_public import EventOrganizerSummarySerializer


from .serializers_registration_admin import (
    EventRegistrationAdminSerializer, EventStaffRegistrationSerializer, EventEligibleMemberSerializer,
)


class EventWriteSerializer(serializers.Serializer):
    registration_audience = serializers.ChoiceField(choices=Event.RegistrationAudience.choices, required=False)
    category_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=50), max_length=20, required=False)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, default='', required=False)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone_name = serializers.CharField(max_length=64, required=False)
    location = serializers.CharField(
        allow_blank=True,
        default='',
        max_length=255,
        required=False,
    )
    location_kind = serializers.ChoiceField(
        choices=Event.LocationKind.choices,
        default=Event.LocationKind.OTHER,
        required=False,
    )
    custom_form = CustomFormSchemaField(allow_null=True, required=False)
    capacity = serializers.IntegerField(default=0, min_value=0, required=False)
    payment_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        default=0,
        required=False,
    )
    is_public = serializers.BooleanField(default=False, required=False)
    registration_requires_approval = serializers.BooleanField(
        default=False, required=False,
    )
    cancellation_cutoff_hours = serializers.IntegerField(
        allow_null=True, default=None, min_value=0, max_value=8760, required=False,
        help_text="Member cancellation closes this many hours before start; null means start.",
    )
    registration_cutoff_at = serializers.DateTimeField(
        allow_null=True, default=None, required=False,
    )
    registration_cutoff_lead_minutes = serializers.IntegerField(
        allow_null=True, default=None, min_value=0, required=False,
    )
    inherit_fields = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted((
            'title', 'description', 'starts_at', 'ends_at', 'location',
            'location_kind', 'custom_form', 'capacity', 'is_public', 'payment_amount',
            'registration_requires_approval', 'registration_audience', 'registration_cutoff_at',
            'registration_cutoff_lead_minutes', 'cancellation_cutoff_hours',
            'image_key',
        ))),
        required=False,
        write_only=True,
    )

    def validate(self, attrs):
        starts_at = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends_at = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if starts_at is not None and ends_at is not None and ends_at < starts_at:
            raise serializers.ValidationError(
                {'ends_at': 'End time must be at or after start time.'}
            )
        cutoff_at = attrs.get(
            'registration_cutoff_at',
            getattr(self.instance, 'registration_cutoff_at', None),
        )
        lead_minutes = attrs.get(
            'registration_cutoff_lead_minutes',
            getattr(self.instance, 'registration_cutoff_lead_minutes', None),
        )
        if cutoff_at is not None and lead_minutes is not None:
            raise serializers.ValidationError({
                'registration_cutoff_at': (
                    'Clear lead minutes before setting an absolute cutoff.'
                ),
                'registration_cutoff_lead_minutes': (
                    'Clear the absolute cutoff before setting lead minutes.'
                ),
            })
        if cutoff_at is not None and starts_at is not None and cutoff_at > starts_at:
            raise serializers.ValidationError({
                'registration_cutoff_at': (
                    'Registration cutoff cannot be after the event starts.'
                )
            })
        return attrs


class EventRegistrationCountsSerializer(serializers.Serializer):
    pending_approval = serializers.IntegerField(read_only=True)
    registered = serializers.IntegerField(read_only=True)
    waitlisted = serializers.IntegerField(read_only=True)
    rejected = serializers.IntegerField(read_only=True)
    cancelled = serializers.IntegerField(read_only=True)
    attended = serializers.IntegerField(read_only=True)


class EventAttendanceMarkSerializer(serializers.Serializer):
    source = serializers.ChoiceField(
        choices=("online", "qr"),
        default="online",
        required=False,
    )


class EventAdminSerializer(serializers.ModelSerializer):
    ticketing_features = serializers.SerializerMethodField()
    makerspace_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    registration_counts = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    organizers = EventOrganizerSummarySerializer(many=True, read_only=True)
    effective_registration_cutoff_at = serializers.SerializerMethodField()
    registration_open = serializers.SerializerMethodField()
    series_summary = serializers.SerializerMethodField()
    offline_checkin_enabled = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            'id',
            'makerspace_id', 'ticketing_features',
            'series_summary',
            'series_revision',
            'series_override_fields',
            'title',
            'description',
            'starts_at',
            'ends_at',
            'timezone_name',
            'location',
            'location_kind',
            'custom_form',
            'capacity',
            'payment_amount',
            'registration_requires_approval',
            'registration_audience', 'category_id', 'tags',
            'cancellation_cutoff_hours',
            'registration_cutoff_at',
            'registration_cutoff_lead_minutes',
            'effective_registration_cutoff_at',
            'registration_open',
            'offline_checkin_enabled',
            'is_public',
            'image_url',
            'status',
            'created_by_id',
            'created_at',
            'updated_at',
            'registration_counts',
            'organizers',
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_ticketing_features(self, obj):
        return [key for key in ("events.invites", "events.ticket_types", "events.promo_codes") if feature_enabled(obj.makerspace, key)]

    # The raw object key is never exposed: staff and public both receive a resolved
    # URL, matching PublicMachineSerializer.
    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        key = obj.image_key
        if obj.series_id and "image_key" not in (obj.series_override_fields or []):
            key = obj.series.image_key
        return public_image_storage.public_url(key) or None

    @extend_schema_field({
        'type': 'object', 'nullable': True,
        'properties': {
            'id': {'type': 'integer'}, 'public_token': {'type': 'string', 'format': 'uuid'},
            'title': {'type': 'string'}, 'timezone': {'type': 'string'},
        },
    })
    def get_series_summary(self, obj):
        if not obj.series_id:
            return None
        return {
            'id': obj.series_id,
            'public_token': obj.series.public_token,
            'title': obj.series.title,
            'timezone': obj.series.recurrence_timezone,
        }

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_effective_registration_cutoff_at(self, obj):
        return effective_registration_cutoff(obj)

    @extend_schema_field(serializers.BooleanField())
    def get_registration_open(self, obj):
        return registration_is_open(obj, timezone.now())

    @extend_schema_field(serializers.BooleanField())
    def get_offline_checkin_enabled(self, obj):
        return feature_enabled(obj.makerspace, "events.offline_checkin")

    @extend_schema_field(EventRegistrationCountsSerializer)
    def get_registration_counts(self, obj):
        annotations = {
            status: getattr(obj, f'{status}_count', None)
            for status in EventRegistration.Status.values
        }
        if all(value is not None for value in annotations.values()):
            return annotations
        return obj.registrations.aggregate(
            **{
                status: Count('id', filter=Q(status=status))
                for status in EventRegistration.Status.values
            }
        )


class EmptyActionSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if data:
            raise serializers.ValidationError(
                {field: 'Unexpected field.' for field in data}
            )
        return value


class EventListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = EventAdminSerializer(many=True)


class EventListWithDefaultsSerializer(EventListResponseSerializer):
    default_registration_audience = serializers.ChoiceField(choices=Event.RegistrationAudience.choices)


class EventRegistrationListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = EventRegistrationAdminSerializer(many=True)
