from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bookings import storage
from apps.bookings.exceptions import BookerNamesRequiresAvailability
from apps.bookings.models import BookableSpace, Booking
from apps.forms_schema.serializers import CustomFormSchemaField
from apps.admin_api.serializers_payment_summary import PaymentSummaryMixin


class BookableSpaceWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(
        choices=BookableSpace.Kind.choices,
        default=BookableSpace.Kind.OTHER,
        required=False,
    )
    description = serializers.CharField(allow_blank=True, default='', required=False)
    capacity = serializers.IntegerField(default=0, min_value=0, required=False)
    location = serializers.CharField(
        allow_blank=True,
        default='',
        max_length=255,
        required=False,
    )
    is_public = serializers.BooleanField(default=False, required=False)
    show_public_availability = serializers.BooleanField(default=False, required=False)
    show_public_booker_names = serializers.BooleanField(default=False, required=False)
    # approval_mode is a booking rule; it is writable ONLY through the dedicated
    # MANAGE_MAKERSPACE booking-rules endpoint, never this MANAGE_BOOKINGS path.
    custom_form = CustomFormSchemaField(
        allow_null=True,
        required=False,
    )
    requester_notifications_enabled = serializers.BooleanField(
        allow_null=True,
        default=None,
        required=False,
    )
    payment_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        default=0,
        required=False,
    )

    def validate(self, attrs):
        availability = attrs.get(
            'show_public_availability',
            getattr(self.instance, 'show_public_availability', False),
        )
        names = attrs.get(
            'show_public_booker_names',
            getattr(self.instance, 'show_public_booker_names', False),
        )
        if names and not availability:
            raise BookerNamesRequiresAvailability()
        return attrs


class BookableSpaceAdminSerializer(serializers.ModelSerializer):
    makerspace_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    image_url = serializers.SerializerMethodField()
    effective_requester_notifications_enabled = serializers.SerializerMethodField()

    class Meta:
        model = BookableSpace
        fields = (
            'id',
            'public_token',
            'makerspace_id',
            'name',
            'kind',
            'description',
            'capacity',
            'location',
            'image_url',
            'is_public',
            'show_public_availability',
            'show_public_booker_names',
            'approval_mode',
            'min_booking_duration_minutes',
            'max_booking_duration_minutes',
            'booking_lead_time_minutes',
            'max_booking_advance_days',
            'custom_form',
            'requester_notifications_enabled',
            'payment_amount',
            'effective_requester_notifications_enabled',
            'is_active',
            'created_by_id',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_image_url(self, obj):
        return storage.public_url(obj.image_key)

    @extend_schema_field(serializers.BooleanField())
    def get_effective_requester_notifications_enabled(self, obj):
        override = obj.requester_notifications_enabled
        if override is not None:
            return override
        return obj.makerspace.booking_requester_notifications_enabled


class BookableSpaceBookingRulesSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookableSpace
        fields = (
            'min_booking_duration_minutes',
            'max_booking_duration_minutes',
            'booking_lead_time_minutes',
            'max_booking_advance_days',
            'approval_mode',
        )


class BookingAdminSerializer(PaymentSummaryMixin, serializers.ModelSerializer):
    space_id = serializers.IntegerField(read_only=True)
    payment = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = (
            'id',
            'public_token',
            'space_id',
            'name',
            'email',
            'phone',
            'starts_at',
            'ends_at',
            'status',
            'note',
            'custom_answers',
            'created_at',
            'payment',
        )
        read_only_fields = fields


class SpaceImagePresignRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)


class SpaceImageUploadSerializer(serializers.Serializer):
    url = serializers.URLField()
    method = serializers.ChoiceField(choices=('PUT',), required=False)
    fields = serializers.DictField(required=False)
    headers = serializers.DictField(required=False)


class SpaceImagePresignResponseSerializer(serializers.Serializer):
    object_key = serializers.CharField()
    upload = SpaceImageUploadSerializer()


class SpaceImageFinalizeRequestSerializer(serializers.Serializer):
    object_key = serializers.CharField(max_length=500)


class EmptyActionSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if data:
            raise serializers.ValidationError(
                {field: 'Unexpected field.' for field in data}
            )
        return value


class BookableSpaceListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = BookableSpaceAdminSerializer(many=True)


class BookingListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = BookingAdminSerializer(many=True)


class BookingListFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Booking.Status.choices, required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        if (
            attrs.get('starts_at')
            and attrs.get('ends_at')
            and attrs['ends_at'] < attrs['starts_at']
        ):
            raise serializers.ValidationError(
                {'ends_at': 'End of window must be at or after its start.'}
            )
        return attrs
