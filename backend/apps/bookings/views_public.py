from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from collections.abc import Mapping
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.bookings import services_bookings
from apps.bookings.models import BookableSpace, Booking
from apps.bookings.services_schedule import occupied_window, published_open_intervals
from apps.bookings.serializers_public import (
    PublicBookableSpaceSerializer,
    PublicBookingInputSerializer,
    PublicBookingResponseSerializer,
    PublicSpaceAvailabilityQuerySerializer,
    PublicSpaceAvailabilitySerializer,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module_for_servable
from apps.makerspaces.lookup import get_public_makerspace
from apps.bookings.access import require_booking_account


LOOSE_ERROR_SCHEMA = {'type': 'object', 'additionalProperties': {}}

PUBLIC_BOOKING_ERRORS = {
    400: OpenApiResponse(LOOSE_ERROR_SCHEMA, description='Invalid request.'),
    404: OpenApiResponse(LOOSE_ERROR_SCHEMA, description='Space not found.'),
    429: OpenApiResponse(LOOSE_ERROR_SCHEMA, description='Rate limit exceeded.'),
}
PUBLIC_BOOKING_SUBMISSION_ERRORS = {
    **PUBLIC_BOOKING_ERRORS,
    401: OpenApiResponse(ErrorSerializer, description='Authentication is required.'),
    403: OpenApiResponse(ErrorSerializer, description='Active account and any existing membership waiver acceptance are required.'),
    409: OpenApiResponse(ErrorSerializer, description='Booking conflict.'),
    423: OpenApiResponse(ErrorSerializer, description='Tenant frozen for migration.'),
    503: OpenApiResponse(ErrorSerializer, description='Tenant write gate unavailable.'),
}


def _public_spaces(makerspace):
    return BookableSpace.objects.filter(
        makerspace=makerspace,
        is_public=True,
        is_active=True,
    )


class PublicBookableSpaceListView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = 'public_read'

    @extend_schema(
        tags=['Public bookings'],
        auth=[],
        request=None,
        responses={
            200: PublicBookableSpaceSerializer(many=True),
            **PUBLIC_BOOKING_ERRORS,
        },
    )
    def get(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module_for_servable(makerspace, 'bookings')
        spaces = _public_spaces(makerspace).order_by('name', 'id')
        return Response(PublicBookableSpaceSerializer(spaces, many=True).data)


class PublicSpaceAvailabilityView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = 'public_read'

    @extend_schema(
        tags=['Public bookings'],
        auth=[],
        request=None,
        parameters=[PublicSpaceAvailabilityQuerySerializer],
        responses={
            200: PublicSpaceAvailabilitySerializer,
            **PUBLIC_BOOKING_ERRORS,
        },
    )
    def get(self, request, makerspace_slug, public_token):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module_for_servable(makerspace, 'bookings')
        space = get_object_or_404(
            _public_spaces(makerspace),
            public_token=public_token,
        )
        query = PublicSpaceAvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        starts_at = query.validated_data['starts_at']
        ends_at = query.validated_data['ends_at']

        availability = None
        if space.show_public_availability:
            # Busy windows contain occupancy only; cleanup settings remain private.
            from datetime import timedelta

            bookings = Booking.objects.filter(
                space=space,
                status=Booking.Status.CONFIRMED,
                starts_at__lt=ends_at + timedelta(minutes=space.buffer_before_minutes),
                ends_at__gt=starts_at - timedelta(minutes=space.buffer_after_minutes),
            ).only('starts_at', 'ends_at', 'name').order_by('starts_at', 'id')
            availability = [
                {
                    'starts_at': occupied_window(space, booking.starts_at, booking.ends_at)[0],
                    'ends_at': occupied_window(space, booking.starts_at, booking.ends_at)[1],
                    'booker_name': (
                        booking.name if space.show_public_booker_names else None
                    ),
                }
                for booking in bookings
            ]

        payload = {
            'public_token': space.public_token,
            'starts_at': starts_at,
            'ends_at': ends_at,
            'timezone': makerspace.timezone,
            'opening_intervals': published_open_intervals(makerspace, starts_at, ends_at),
            'availability': availability,
        }
        return Response(PublicSpaceAvailabilitySerializer(payload).data)


class PublicBookingSubmissionView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = 'booking_submit'

    @extend_schema(
        tags=['Public bookings'],
        request=PublicBookingInputSerializer,
        responses={
            201: PublicBookingResponseSerializer,
            **PUBLIC_BOOKING_SUBMISSION_ERRORS,
        },
    )
    def post(self, request, makerspace_slug, public_token):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module_for_servable(makerspace, 'bookings')
        space = get_object_or_404(
            _public_spaces(makerspace),
            public_token=public_token,
        )
        require_booking_account(request.user, makerspace)

        if not isinstance(request.data, Mapping):
            raise serializers.ValidationError({'non_field_errors': ['Expected an object.']})
        website = request.data.get('website')
        if website and str(website).strip():
            expected_status = (
                Booking.Status.CONFIRMED
                if space.approval_mode == BookableSpace.ApprovalMode.INSTANT
                else Booking.Status.PENDING
            )
            return Response(
                {'status': expected_status},
                status=status.HTTP_201_CREATED,
            )

        serializer = PublicBookingInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services_bookings.create_booking(
            space,
            member=request.user,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            PublicBookingResponseSerializer(booking).data,
            status=status.HTTP_201_CREATED,
        )
