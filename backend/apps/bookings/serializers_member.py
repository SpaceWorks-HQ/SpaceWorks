"""Member booking projections contain only the caller's own reservations."""

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bookings.models import Booking
from apps.bookings.services_schedule import cancellation_cutoff, member_can_cancel


class MemberBookingSerializer(serializers.ModelSerializer):
    space_name = serializers.CharField(source='space.name', read_only=True)
    timezone = serializers.CharField(source='space.makerspace.timezone', read_only=True)
    cancellation_cutoff_at = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = ('public_token', 'space_name', 'timezone', 'starts_at', 'ends_at',
                  'status', 'cancellation_cutoff_at', 'can_cancel')
        read_only_fields = fields

    @extend_schema_field(serializers.DateTimeField())
    def get_cancellation_cutoff_at(self, booking):
        return cancellation_cutoff(booking)

    @extend_schema_field(serializers.BooleanField())
    def get_can_cancel(self, booking):
        return member_can_cancel(booking, now=self.context.get('now') or timezone.now())


class MemberBookingListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = MemberBookingSerializer(many=True)


class MemberBookingFilterSerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=('upcoming', 'past'), default='upcoming')
