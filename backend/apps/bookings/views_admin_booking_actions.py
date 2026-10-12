from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.bookings.serializers_admin import (
    BookingAdminSerializer,
    EmptyActionSerializer,
)
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.bookings import services
from apps.bookings.models import Booking
from apps.hardware_requests.view_helpers import (
    ERROR_400,
    ERROR_401,
    ERROR_403,
    ERROR_404,
    ERROR_409,
)
from apps.makerspaces.guards import require_module
from apps.payments.models import Payment


SCOPED_ERROR_RESPONSES = {
    401: ERROR_401,
    403: ERROR_403,
    404: ERROR_404,
}
VALIDATED_ERROR_RESPONSES = {
    400: ERROR_400,
    **SCOPED_ERROR_RESPONSES,
}


class _BookingPagination(PageNumberPagination):
    page_size = 24
    page_size_query_param = 'page_size'
    max_page_size = 500


def _manageable_booking(actor, pk):
    booking = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_BOOKINGS,
            Booking.objects.select_related('space__makerspace'),
            field='space__makerspace_id',
        ),
        pk=pk,
    )
    require_module(booking.space.makerspace, 'bookings')
    if not rbac.can(
        actor,
        rbac.Action.MANAGE_BOOKINGS,
        booking.space.makerspace_id,
    ):
        raise PermissionDenied()
    return booking


class _BookingActionView(APIView):
    permission_classes = [IsActiveStaff]
    operation = None

    def execute(self, request, pk):
        booking = _manageable_booking(request.user, pk)
        serializer = EmptyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = self.operation(booking, actor=request.user)
        context = scoped_payment_context(
            request.user,
            rbac.Action.MANAGE_BOOKINGS,
            Payment.SubjectType.BOOKING,
            [booking.pk],
        )
        return Response(BookingAdminSerializer(booking, context=context).data)


class BookingCancelView(_BookingActionView):
    operation = staticmethod(services.cancel_booking)

    @extend_schema(
        tags=['Admin bookings'],
        summary='Cancel a booking',
        request=EmptyActionSerializer,
        responses={
            200: BookingAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


class BookingApproveView(_BookingActionView):
    operation = staticmethod(services.approve_booking)

    @extend_schema(
        tags=['Admin bookings'],
        summary='Approve a pending booking',
        request=EmptyActionSerializer,
        responses={
            200: BookingAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


class BookingRejectView(_BookingActionView):
    operation = staticmethod(services.reject_booking)

    @extend_schema(
        tags=['Admin bookings'],
        summary='Reject a pending booking',
        request=EmptyActionSerializer,
        responses={
            200: BookingAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


class BookingCompleteView(_BookingActionView):
    operation = staticmethod(services.complete_booking)

    @extend_schema(
        tags=['Admin bookings'],
        summary='Complete a booking',
        request=EmptyActionSerializer,
        responses={
            200: BookingAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


class BookingNoShowView(_BookingActionView):
    operation = staticmethod(services.mark_no_show)

    @extend_schema(
        tags=['Admin bookings'],
        summary='Mark a booking as no-show',
        request=EmptyActionSerializer,
        responses={
            200: BookingAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)
