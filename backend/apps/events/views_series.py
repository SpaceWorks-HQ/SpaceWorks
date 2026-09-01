from django.db.models import Count, Min, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.events.models import Event, EventSeries
from apps.events.serializers_admin import EmptyActionSerializer, EventAdminSerializer, EventListResponseSerializer
from apps.events.serializers_series import (
    EventSeriesDetailSerializer,
    EventSeriesListResponseSerializer,
    EventSeriesMutationResponseSerializer,
    EventSeriesSummarySerializer,
    EventSeriesWriteSerializer,
)
from apps.events.series_authority import can_manage_series, organizer_series_q
from apps.events import services_series
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace


SERIES_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid recurring event series."),
    401: OpenApiResponse(ErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(ErrorSerializer, description="Event management access denied."),
    404: OpenApiResponse(ErrorSerializer, description="Event series not found."),
    409: OpenApiResponse(ErrorSerializer, description="Series state conflict."),
    429: OpenApiResponse(ErrorSerializer, description="Rate limit exceeded."),
}


class _Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def _visible_makerspace(actor, makerspace_id):
    space = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor, rbac.Action.MANAGE_EVENTS, Makerspace.objects.all(), field="id"
        ),
        pk=makerspace_id,
    )
    require_module(space, "events")
    if not rbac.can(actor, rbac.Action.MANAGE_EVENTS, space.pk):
        raise PermissionDenied()
    return space


def manageable_series(actor, pk):
    venue = rbac.scope_by_visibility_or_action(
        actor, rbac.Action.MANAGE_EVENTS, EventSeries.objects.all(), field="makerspace_id"
    )
    series = get_object_or_404(
        EventSeries.objects.select_related("makerspace").filter(
            Q(pk__in=venue.values("pk")) | organizer_series_q(actor)
        ).distinct(),
        pk=pk,
    )
    require_module(series.makerspace, "events")
    if not can_manage_series(actor, series):
        raise PermissionDenied()
    return series


def _mutation(series, *, created=(), removed=(), affected=0):
    return Response({
        "series": EventSeriesDetailSerializer(series).data,
        "created_occurrence_ids": [row.pk for row in created],
        "removed_occurrence_ids": list(removed),
        "affected_count": affected,
    })


class EventSeriesListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin event series"], summary="List recurring event series", request=None,
        responses={200: EventSeriesListResponseSerializer, **SERIES_ERRORS},
    )
    def get(self, request, makerspace_id):
        space = _visible_makerspace(request.user, makerspace_id)
        queryset = rbac.scope_by_action(
            request.user, rbac.Action.MANAGE_EVENTS,
            EventSeries.objects.filter(makerspace=space), field="makerspace_id",
        ).annotate(
            next_occurrence_at=Min(
                "occurrences__starts_at",
                filter=Q(occurrences__status__in=(Event.Status.DRAFT, Event.Status.PUBLISHED)),
            ),
            future_occurrence_count=Count(
                "occurrences",
                filter=Q(occurrences__status__in=(Event.Status.DRAFT, Event.Status.PUBLISHED)),
                distinct=True,
            ),
        ).order_by("dtstart_local_date", "dtstart_local_time", "pk")
        paginator = _Pagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(EventSeriesSummarySerializer(page, many=True).data)

    @extend_schema(
        tags=["Admin event series"], summary="Create a recurring event series",
        request=EventSeriesWriteSerializer,
        responses={201: EventSeriesMutationResponseSerializer, **SERIES_ERRORS},
    )
    def post(self, request, makerspace_id):
        space = _visible_makerspace(request.user, makerspace_id)
        serializer = EventSeriesWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values.pop("effective_from", None)
        series, created = services_series.create_series(
            makerspace=space, actor=request.user, **values
        )
        response = _mutation(series, created=created, affected=len(created))
        response.status_code = status.HTTP_201_CREATED
        return response


class EventSeriesDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin event series"], request=None, responses={200: EventSeriesDetailSerializer, **SERIES_ERRORS})
    def get(self, request, pk):
        return Response(EventSeriesDetailSerializer(manageable_series(request.user, pk)).data)

    @extend_schema(tags=["Admin event series"], request=EventSeriesWriteSerializer, responses={200: EventSeriesMutationResponseSerializer, **SERIES_ERRORS})
    def patch(self, request, pk):
        series = manageable_series(request.user, pk)
        serializer = EventSeriesWriteSerializer(series, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        effective_from = changes.pop("effective_from", None)
        series, created, removed = services_series.update_series(
            series, actor=request.user, effective_from=effective_from, **changes
        )
        return _mutation(series, created=created, removed=removed, affected=len(created) + len(removed))


class EventSeriesOccurrenceListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin event series"], request=None, responses={200: EventListResponseSerializer, **SERIES_ERRORS})
    def get(self, request, pk):
        series = manageable_series(request.user, pk)
        queryset = Event.objects.filter(series=series).select_related("series").order_by("starts_at", "pk")
        paginator = _Pagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(EventAdminSerializer(page, many=True).data)


class _Action(APIView):
    permission_classes = [IsActiveStaff]
    operation = None

    def execute(self, request, pk):
        EmptyActionSerializer(data=request.data).is_valid(raise_exception=True)
        result = self.operation(manageable_series(request.user, pk), actor=request.user)
        if isinstance(result, tuple):
            series, value = result
            created = value if isinstance(value, list) else ()
            return _mutation(series, created=created, affected=len(value) if isinstance(value, list) else value)
        return _mutation(result)


class EventSeriesPublishView(_Action):
    operation = staticmethod(services_series.publish_series)

    @extend_schema(tags=["Admin event series"], request=EmptyActionSerializer, responses={200: EventSeriesMutationResponseSerializer, **SERIES_ERRORS})
    def post(self, request, pk):
        return self.execute(request, pk)


class EventSeriesCancelView(_Action):
    operation = staticmethod(services_series.cancel_series)

    @extend_schema(tags=["Admin event series"], request=EmptyActionSerializer, responses={200: EventSeriesMutationResponseSerializer, **SERIES_ERRORS})
    def post(self, request, pk):
        return self.execute(request, pk)


class EventSeriesCompleteView(_Action):
    operation = staticmethod(services_series.complete_series)

    @extend_schema(tags=["Admin event series"], request=EmptyActionSerializer, responses={200: EventSeriesMutationResponseSerializer, **SERIES_ERRORS})
    def post(self, request, pk):
        return self.execute(request, pk)


class EventSeriesExtendView(_Action):
    operation = staticmethod(services_series.extend_series)

    @extend_schema(tags=["Admin event series"], request=EmptyActionSerializer, responses={200: EventSeriesMutationResponseSerializer, **SERIES_ERRORS})
    def post(self, request, pk):
        return self.execute(request, pk)
