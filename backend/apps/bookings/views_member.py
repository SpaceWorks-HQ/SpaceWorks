"""Authenticated booking history/cancellation; identity never matches contact text."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.apiclients.throttling import MemberPrincipalRateThrottle
from apps.bookings.models import Booking
from apps.bookings.serializers_admin import EmptyActionSerializer
from apps.bookings.serializers_member import (
    MemberBookingFilterSerializer, MemberBookingListSerializer, MemberBookingSerializer,
)
from apps.bookings.services_bookings import cancel_booking
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module_for_servable
from apps.makerspaces.lookup import get_public_makerspace
from apps.presence.guard import require_active_account
from apps.bookings.serializers_reschedule import BookingRescheduleSerializer
from apps.bookings.services_reschedule import reschedule_booking


ERRORS = {
    400: OpenApiResponse({'type': 'object', 'additionalProperties': {}}, description='Invalid request or bookings disabled.'),
    401: OpenApiResponse(ErrorSerializer, description='Sign-in required.'),
    403: OpenApiResponse(ErrorSerializer, description='Active account required.'),
    404: OpenApiResponse(ErrorSerializer, description='Makerspace or own booking not found.'),
    429: OpenApiResponse(ErrorSerializer, description='Rate limit exceeded.'),
}


def own_bookings(request, slug):
    makerspace = get_public_makerspace(slug)
    require_module_for_servable(makerspace, 'bookings')
    require_active_account(request.user, makerspace)
    return rbac.scope_personal_bookings(
        request.user,
        Booking.objects.select_related('space__makerspace').filter(
            space__makerspace=makerspace, member=request.user,
        ), makerspace_id=makerspace.pk,
    )


class MemberBookingListView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = 'public_read'

    @extend_schema(tags=['Member bookings'], request=None,
                   parameters=[MemberBookingFilterSerializer, OpenApiParameter('page', int)],
                   responses={200: MemberBookingListSerializer, **ERRORS})
    def get(self, request, makerspace_slug):
        bookings = own_bookings(request, makerspace_slug)
        query = MemberBookingFilterSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        now = timezone.now()
        if query.validated_data['period'] == 'past':
            bookings = bookings.filter(ends_at__lte=now).order_by('-starts_at', '-id')
        else:
            bookings = bookings.filter(ends_at__gt=now).order_by('starts_at', 'id')
        paginator = PageNumberPagination()
        paginator.page_size = 24
        rows = paginator.paginate_queryset(bookings, request, view=self)
        return paginator.get_paginated_response(
            MemberBookingSerializer(rows, many=True, context={'now': now}).data,
        )


class MemberBookingCancelView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = 'booking_submit'

    @extend_schema(tags=['Member bookings'], request=EmptyActionSerializer,
                   responses={200: MemberBookingSerializer, **ERRORS,
                              423: OpenApiResponse(ErrorSerializer, description='Tenant frozen for migration.'),
                              503: OpenApiResponse(ErrorSerializer, description='Tenant write gate unavailable.'),
                              409: OpenApiResponse(ErrorSerializer, description='Cancellation cutoff or state conflict.')})
    def post(self, request, makerspace_slug, public_token):
        booking = get_object_or_404(own_bookings(request, makerspace_slug), public_token=public_token)
        body = EmptyActionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        cancelled = cancel_booking(booking, actor=request.user, member_cancel=True)
        return Response(MemberBookingSerializer(cancelled).data)


class MemberBookingRescheduleView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = 'booking_submit'

    @extend_schema(tags=['Member bookings'], request=BookingRescheduleSerializer,
                   responses={200: MemberBookingSerializer, **ERRORS,
                              409: OpenApiResponse(ErrorSerializer, description='Cutoff, state or slot conflict.'),
                              423: OpenApiResponse(ErrorSerializer, description='Tenant frozen.'),
                              503: OpenApiResponse(ErrorSerializer, description='Tenant gate unavailable.')})
    def post(self, request, makerspace_slug, public_token):
        booking = get_object_or_404(own_bookings(request, makerspace_slug), public_token=public_token)
        serializer = BookingRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        moved = reschedule_booking(booking, actor=request.user, **serializer.validated_data)
        return Response(MemberBookingSerializer(moved).data)
