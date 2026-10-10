"""Minimal type choices for booking editors, under their existing booking authority."""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.bookings.views_admin_spaces import _visible_makerspace
from apps.hardware_requests.view_helpers import ERROR_401, ERROR_403, ERROR_404
from apps.makerspaces.guards import require_module


class BookingMachineTypeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class BookingMachineTypePageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = BookingMachineTypeSerializer(many=True)


class BookingMachineTypeListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'], summary='List machine type choices for booking spaces',
        request=None, parameters=[OpenApiParameter('page', int, description='Page number.')],
        responses={200: BookingMachineTypePageSerializer, 400: OpenApiResponse(
                       {'type': 'object', 'additionalProperties': {}},
                       description='Bookings or machines module disabled.'),
                   401: ERROR_401, 403: ERROR_403, 404: ERROR_404},
    )
    def get(self, request, makerspace_id):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        require_module(makerspace, 'machines')
        # Lazy import preserves the bookings-only deployment. These choices expose
        # names/ids, never machine inventories, management capabilities or documents.
        from apps.machines.models import MachineType

        owned = rbac.scope_by_action(
            request.user, rbac.Action.MANAGE_BOOKINGS, MachineType.objects.all(),
        ).filter(makerspace=makerspace)
        rows = (owned | MachineType.objects.filter(makerspace__isnull=True)).order_by('name', 'pk')
        paginator = PageNumberPagination()
        paginator.page_size = 24
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(BookingMachineTypeSerializer(page, many=True).data)
