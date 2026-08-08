from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.events.models import Event, EventRegistration
from apps.forms_schema.serializers import CustomFormSchemaField
from apps.admin_api.serializers_payment_summary import PaymentSummaryMixin


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

    def validate(self, attrs):
        starts_at = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends_at = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if starts_at is not None and ends_at is not None and ends_at < starts_at:
            raise serializers.ValidationError(
                {'ends_at': 'End time must be at or after start time.'}
            )
        return attrs


class EventRegistrationCountsSerializer(serializers.Serializer):
    registered = serializers.IntegerField(read_only=True)
    waitlisted = serializers.IntegerField(read_only=True)
    cancelled = serializers.IntegerField(read_only=True)
    attended = serializers.IntegerField(read_only=True)


class EventAdminSerializer(serializers.ModelSerializer):
    makerspace_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    registration_counts = serializers.SerializerMethodField()

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
            'is_public',
            'status',
            'created_by_id',
            'created_at',
            'updated_at',
            'registration_counts',
        )
        read_only_fields = fields

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
