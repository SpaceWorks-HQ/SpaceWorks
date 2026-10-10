"""Staff creation uses the same locked service and certification gate as self-booking."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.bookings import services
from apps.bookings.serializers_admin import BookingAdminSerializer
from apps.bookings.serializers_staff_booking import (
    BookingEligibleMemberListSerializer, BookingEligibleMemberSerializer,
    StaffBookingInputSerializer,
)
from apps.bookings.views_admin_spaces import manageable_space
from apps.hardware_requests.view_helpers import ERROR_401, ERROR_403, ERROR_404, ERROR_409
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment
from apps.presence.guard import require_active_member


ERRORS = {
    400: OpenApiResponse(
        {'type': 'object', 'additionalProperties': {}},
        description='Invalid input or bookings module disabled.',
    ),
    401: ERROR_401, 403: ERROR_403, 404: ERROR_404,
}


def _members(actor, space):
    return rbac.scope_by_action(
        actor, rbac.Action.MANAGE_BOOKINGS,
        MakerspaceMembership.objects.select_related('user').filter(
            makerspace_id=space.makerspace_id, status='active',
            user__is_active=True, user__access_status=User.AccessStatus.ACTIVE,
        ),
    )


class StaffBookingCreateMixin:
    @extend_schema(
        tags=['Admin bookings'], summary='Book a space on behalf of an active member',
        request=StaffBookingInputSerializer,
        responses={201: BookingAdminSerializer, **ERRORS, 409: ERROR_409,
                   423: OpenApiResponse(ErrorSerializer, description='Tenant frozen for migration.'),
                   503: OpenApiResponse(ErrorSerializer, description='Tenant write gate unavailable.')},
    )
    def post(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        serializer = StaffBookingInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        membership = get_object_or_404(_members(request.user, space), user_id=values.pop('member_id'))
        # Booking ahead is allowed; membership, active standing and current waiver remain mandatory.
        require_active_member(membership.user, space.makerspace)
        booking = services.create_booking(space, member=membership.user, actor=request.user, **values)
        context = scoped_payment_context(
            request.user, rbac.Action.MANAGE_BOOKINGS, Payment.SubjectType.BOOKING, [booking.pk],
        )
        return Response(BookingAdminSerializer(booking, context=context).data, status=201)


class _MemberPagination(PageNumberPagination):
    page_size = 24


class BookingEligibleMembersView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'], summary='List active members for staff booking', request=None,
        parameters=[OpenApiParameter('page', int)],
        responses={200: BookingEligibleMemberListSerializer, **ERRORS},
    )
    def get(self, request, pk):
        space = manageable_space(request.user, pk)
        rows = _members(request.user, space).order_by('user__display_name', 'user__username', 'pk')
        paginator = _MemberPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(BookingEligibleMemberSerializer(page, many=True).data)
