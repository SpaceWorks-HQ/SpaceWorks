from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.events.models import Event, EventRegistration
from apps.events.capacity import effective_registration_cutoff, registration_is_open
from apps.forms_schema.serializers import CustomFormSchemaField
from apps.inventory import public_image_storage
from apps.admin_api.serializers_payment_summary import PaymentSummaryMixin
from apps.events.serializers_public import EventOrganizerSummarySerializer


class EventWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, default='', required=False)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
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
    registration_cutoff_at = serializers.DateTimeField(
        allow_null=True, default=None, required=False,
    )
    registration_cutoff_lead_minutes = serializers.IntegerField(
        allow_null=True, default=None, min_value=0, required=False,
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
        choices=("staff", "qr"),
        default="staff",
        required=False,
    )


class EventAdminSerializer(serializers.ModelSerializer):
    makerspace_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    registration_counts = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    organizers = EventOrganizerSummarySerializer(many=True, read_only=True)
    effective_registration_cutoff_at = serializers.SerializerMethodField()
    registration_open = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            'id',
            'makerspace_id',
            'title',
            'description',
            'starts_at',
            'ends_at',
            'location',
            'location_kind',
            'custom_form',
            'capacity',
            'payment_amount',
            'registration_requires_approval',
            'registration_cutoff_at',
            'registration_cutoff_lead_minutes',
            'effective_registration_cutoff_at',
            'registration_open',
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

    # The raw object key is never exposed: staff and public both receive a resolved
    # URL, matching PublicMachineSerializer.
    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        return public_image_storage.public_url(obj.image_key) or None

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_effective_registration_cutoff_at(self, obj):
        return effective_registration_cutoff(obj)

    @extend_schema_field(serializers.BooleanField())
    def get_registration_open(self, obj):
        return registration_is_open(obj, timezone.now())

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


class EventRegistrationAdminSerializer(PaymentSummaryMixin, serializers.ModelSerializer):
    event_id = serializers.IntegerField(read_only=True)
    payment = serializers.SerializerMethodField()

    class Meta:
        model = EventRegistration
        fields = (
            'id', 'event_id', 'name', 'email', 'phone', 'custom_answers',
            'status', 'created_at', 'payment',
        )
        read_only_fields = fields


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


class EventRegistrationListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = EventRegistrationAdminSerializer(many=True)


class EventStaffRegistrationSerializer(serializers.Serializer):
    """Staff registering a member of this makerspace for an event.

    `member_id` only. Contact details are copied off the account by the registration
    service, so a staffer cannot record an attendee under a name and email that belong
    to nobody — which is what makes the attendee list usable as an accountability record
    rather than free text.
    """

    member_id = serializers.IntegerField()
    custom_answers = serializers.JSONField(required=False, allow_null=True)
    # Used only when the account carries no number of its own. A registration must have
    # a contact number, so without this a member who never entered one could not be
    # registered by anybody — a dead end the person at the desk can simply ask about.
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default='')
    # Same fallback shape, for the same reason: `EventRegistration.email` is non-blank,
    # and a walk-in may have been created with a name and nothing else. Without this,
    # exactly the members this program made registrable could never be registered.
    email = serializers.EmailField(required=False, allow_blank=True, default='')


class EventEligibleMemberSerializer(serializers.Serializer):
    """A picker row. Name and id only — a roster is not a contact export."""

    member_id = serializers.IntegerField()
    display_name = serializers.CharField()
