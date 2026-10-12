from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.bookings.serializers_staff_booking import StaffBookingInputSerializer
from apps.bookings.services_recurrence import create_recurring_bookings
from apps.bookings.views_admin_booking_create import _members
from apps.bookings.views_admin_spaces import manageable_space
from apps.presence.guard import require_active_member
from apps.openapi_errors import errors


class RecurringBookingInputSerializer(StaffBookingInputSerializer):
    count = serializers.IntegerField(min_value=2, max_value=52)
    interval_weeks = serializers.IntegerField(min_value=1, max_value=12, default=1)


class OccurrenceResultSerializer(serializers.Serializer):
    occurrence = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    booking_id = serializers.IntegerField(allow_null=True)
    status = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)


class RecurrenceResultSerializer(serializers.Serializer):
    occurrences = OccurrenceResultSerializer(many=True)


class StaffRecurringBookingView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=['Admin bookings'], request=RecurringBookingInputSerializer,
                   responses={200: RecurrenceResultSerializer, **errors(400, 401, 403, 404, 409, 423, 503)},
                   description='Create a finite weekly series in makerspace local time. Each occurrence has its own flat charge and cancellation. Conflicts are reported, never silently skipped.')
    def post(self, request, pk):
        space = manageable_space(request.user, pk)
        serializer = RecurringBookingInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        membership = get_object_or_404(_members(request.user, space), user_id=values.pop('member_id'))
        require_active_member(membership.user, space.makerspace)
        result = create_recurring_bookings(space, actor=request.user, member=membership.user, **values)
        return Response(RecurrenceResultSerializer({'occurrences': result}).data)
