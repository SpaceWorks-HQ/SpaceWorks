from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.list_options import ORDER_PAGE_PARAMETERS, order_list
from apps.admin_api.permissions import IsActiveStaff
from apps.bookings.serializers_admin import (
    BookingAdminSerializer,
    BookingListFilterSerializer,
    BookingListResponseSerializer,
)
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.bookings.views_admin_spaces import manageable_space
from apps.bookings.models import Booking
from apps.payments.models import Payment

from .views_admin_booking_actions import _BookingPagination, VALIDATED_ERROR_RESPONSES
from .views_admin_booking_create import StaffBookingCreateMixin


class SpaceBookingListView(StaffBookingCreateMixin, APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='List bookings for a space',
        request=None,
        parameters=[BookingListFilterSerializer, *ORDER_PAGE_PARAMETERS],
        responses={
            200: BookingListResponseSerializer,
            **VALIDATED_ERROR_RESPONSES,
        },
    )
    def get(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        filters = BookingListFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        queryset = rbac.scope_by_action(
            request.user,
            rbac.Action.MANAGE_BOOKINGS,
            Booking.objects.filter(space=space),
            field='space__makerspace_id',
        )
        data = filters.validated_data
        if data.get('booking_id'):
            queryset = queryset.filter(pk=data['booking_id'])
        if data.get('status'):
            queryset = queryset.filter(status=data['status'])
        if data.get('starts_at'):
            queryset = queryset.filter(starts_at__gte=data['starts_at'])
        if data.get('ends_at'):
            queryset = queryset.filter(ends_at__lte=data['ends_at'])
        queryset = order_list(queryset, request.query_params, {"starts_at", "status", "created_at"}, "starts_at")
        paginator = _BookingPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        context = scoped_payment_context(
            request.user,
            rbac.Action.MANAGE_BOOKINGS,
            Payment.SubjectType.BOOKING,
            [booking.pk for booking in page],
        )
        return Response(
            {
                'count': paginator.page.paginator.count,
                'next': paginator.get_next_link(),
                'previous': paginator.get_previous_link(),
                'results': BookingAdminSerializer(
                    page,
                    many=True,
                    context=context,
                ).data,
            }
        )


