"""Inputs and minimal identity choices for staff booking on behalf of a member."""

from collections.abc import Mapping

from rest_framework import serializers

from apps.bookings.serializers_public import PublicBookingInputSerializer


class StaffBookingInputSerializer(PublicBookingInputSerializer):
    member_id = serializers.IntegerField(min_value=1, max_value=9223372036854775807)
    note = serializers.CharField(max_length=5000, allow_blank=True, required=False)
    certification_override_reason = serializers.CharField(
        max_length=1000, allow_blank=True, required=False,
        help_text='Requires existing authority over the linked machine type; audited.',
    )

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: 'Unexpected field.' for key in sorted(unknown)})
        return super().to_internal_value(data)


class BookingEligibleMemberSerializer(serializers.Serializer):
    member_id = serializers.IntegerField(source='user_id', read_only=True)
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, obj) -> str:
        return obj.user.display_name or obj.user.get_full_name() or obj.user.username


class BookingEligibleMemberListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = BookingEligibleMemberSerializer(many=True)
