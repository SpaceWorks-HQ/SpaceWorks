from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bookings import storage
from apps.bookings.models import BookableSpace, Booking


PUBLIC_BOOKABLE_SPACE_FIELDS = (
    'public_token',
    'name',
    'kind',
    'description',
    'capacity',
    'location',
    'image_url',
    'approval_mode',
    'custom_form',
    'show_public_availability',
    'show_public_booker_names',
)


class PublicBookableSpaceSerializer(serializers.Serializer):
    public_token = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    kind = serializers.ChoiceField(
        choices=BookableSpace.Kind.choices,
        read_only=True,
    )
    description = serializers.CharField(read_only=True)
    capacity = serializers.IntegerField(min_value=0, read_only=True)
    location = serializers.CharField(read_only=True)
    image_url = serializers.SerializerMethodField()
    approval_mode = serializers.ChoiceField(
        choices=BookableSpace.ApprovalMode.choices,
        read_only=True,
    )
    custom_form = serializers.JSONField(allow_null=True, read_only=True)
    show_public_availability = serializers.BooleanField(read_only=True)
    show_public_booker_names = serializers.BooleanField(read_only=True)

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_image_url(self, obj):
        return storage.public_url(obj.image_key)


class PublicSpaceAvailabilityQuerySerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        errors = {}
        for field in ('starts_at', 'ends_at'):
            raw = self.initial_data.get(field)
            parsed = parse_datetime(raw) if isinstance(raw, str) else raw
            if parsed is None or timezone.is_naive(parsed):
                errors[field] = 'Datetime must include a timezone offset.'
        if errors:
            raise serializers.ValidationError(errors)

        starts_at = attrs['starts_at']
        ends_at = attrs['ends_at']
        if ends_at <= starts_at:
            raise serializers.ValidationError(
                {'ends_at': 'End time must be after start time.'}
            )
        if ends_at <= timezone.now():
            raise serializers.ValidationError(
                {'ends_at': 'End time must be in the future.'}
            )
        if ends_at - starts_at > timedelta(days=31):
            raise serializers.ValidationError(
                {'ends_at': 'Availability window cannot exceed 31 days.'}
            )
        return attrs


class PublicAvailabilityIntervalSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    booker_name = serializers.CharField(allow_null=True, read_only=True)


class PublicOpeningIntervalSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)


class PublicSpaceAvailabilitySerializer(serializers.Serializer):
    public_token = serializers.UUIDField(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    timezone = serializers.CharField(read_only=True)
    opening_intervals = PublicOpeningIntervalSerializer(
        many=True, read_only=True,
        help_text='Open windows in UTC, accounting for makerspace hours and dated exceptions.',
    )
    availability = PublicAvailabilityIntervalSerializer(
        many=True,
        allow_null=True,
        read_only=True,
    )


class PublicBookingInputSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(write_only=True)
    ends_at = serializers.DateTimeField(write_only=True)
    custom_answers = serializers.JSONField(
        allow_null=True,
        required=False,
        write_only=True,
    )

    def validate(self, attrs):
        errors = {}
        for field in ('starts_at', 'ends_at'):
            raw = self.initial_data.get(field)
            parsed = parse_datetime(raw) if isinstance(raw, str) else raw
            if parsed is None or timezone.is_naive(parsed):
                errors[field] = 'Datetime must include a timezone offset.'
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class PublicBookingResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(Booking.Status.PENDING, Booking.Status.CONFIRMED),
        read_only=True,
    )
