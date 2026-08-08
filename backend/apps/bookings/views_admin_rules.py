from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.bookings.serializers_admin import (
    BookableSpaceBookingRulesSerializer,
)
from apps.bookings import services
from apps.bookings.models import BookableSpace
from apps.hardware_requests.view_helpers import (
    ERROR_403,
    ERROR_404,
    ERROR_409,
)
from apps.makerspaces.guards import require_module


# The rules serializer/service return DRF field-error maps (e.g.
# {"max_booking_duration_minutes": [...]}), and require_module returns a
# {"module": [...]} map — neither matches the {detail, code} HardwareRequestError
# shape, so document 400 as a loose validation-error object (mirrors events).
RULES_ERROR_400 = OpenApiResponse(
    {'type': 'object', 'additionalProperties': {}},
    description='Invalid booking-rule values or bookings module disabled.',
)


class BookableSpaceBookingRulesView(APIView):
    permission_classes = [IsActiveStaff]

    def _resolve(self, actor, pk):
        space = get_object_or_404(
            rbac.scope_by_action(
                actor,
                rbac.Action.MANAGE_MAKERSPACE,
                BookableSpace.objects.select_related('makerspace'),
                field='makerspace_id',
            ),
            pk=pk,
        )
        require_module(space.makerspace, 'bookings')
        return space

    @extend_schema(
        tags=['Admin bookings'],
        summary='Retrieve booking rules for a space',
        request=None,
        responses={
            200: BookableSpaceBookingRulesSerializer,
            400: RULES_ERROR_400,
            403: ERROR_403,
            404: ERROR_404,
        },
    )
    def get(self, request, pk):
        space = self._resolve(request.user, pk)
        return Response(BookableSpaceBookingRulesSerializer(space).data)

    @extend_schema(
        tags=['Admin bookings'],
        summary='Update booking rules for a space',
        request=BookableSpaceBookingRulesSerializer,
        responses={
            200: BookableSpaceBookingRulesSerializer,
            400: RULES_ERROR_400,
            403: ERROR_403,
            404: ERROR_404,
            409: ERROR_409,
        },
    )
    def patch(self, request, pk):
        space = self._resolve(request.user, pk)
        serializer = BookableSpaceBookingRulesSerializer(
            space,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        space = services.update_booking_rules(
            space,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(BookableSpaceBookingRulesSerializer(space).data)
