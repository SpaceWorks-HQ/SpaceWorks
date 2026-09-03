from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.events.models import EventSeriesCollaborator
from apps.events.serializers_series_collaboration import (
    SeriesCollaborationInboxSerializer,
    SeriesCollaborationRespondSerializer,
    SeriesCollaboratorReplaceSerializer,
    SeriesCollaboratorSerializer,
)
from apps.events import services_series_collaboration
from apps.events.series_authority import organizer_series_q
from apps.events.views_series import manageable_series
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid collaboration request."),
    401: OpenApiResponse(ErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(ErrorSerializer, description="Event management access denied."),
    404: OpenApiResponse(ErrorSerializer, description="Series collaboration not found."),
    409: OpenApiResponse(ErrorSerializer, description="Collaboration state conflict."),
    429: OpenApiResponse(ErrorSerializer, description="Rate limit exceeded."),
}


def _collaborator_space(actor, makerspace_id):
    space = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor, rbac.Action.MANAGE_EVENTS, Makerspace.objects.all(), field="id"
        ), pk=makerspace_id,
    )
    require_module(space, "events")
    if not rbac.can(actor, rbac.Action.MANAGE_EVENTS, space.pk):
        raise PermissionDenied()
    return space


def _manageable_invitation(actor, pk):
    row = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor, rbac.Action.MANAGE_EVENTS,
            servable_queryset(EventSeriesCollaborator.objects.filter(
                series__makerspace__enabled_modules__contains=["events"]
            ), relation="series__makerspace").select_related("makerspace", "series__makerspace"),
            field="makerspace_id",
        ), pk=pk,
    )
    require_module(row.makerspace, "events")
    if not rbac.can(actor, rbac.Action.MANAGE_EVENTS, row.makerspace_id):
        raise PermissionDenied()
    return row


class EventSeriesCollaboratorListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin event series"], request=None, responses={200: SeriesCollaboratorSerializer(many=True), **ERRORS})
    def get(self, request, pk):
        series = manageable_series(request.user, pk)
        rows = servable_queryset(
            series.collaborators.select_related("makerspace"), relation="makerspace"
        ).order_by("makerspace__slug", "pk")
        return Response(SeriesCollaboratorSerializer(rows, many=True).data)

    @extend_schema(tags=["Admin event series"], request=SeriesCollaboratorReplaceSerializer, responses={200: SeriesCollaboratorSerializer(many=True), **ERRORS})
    def put(self, request, pk):
        series = manageable_series(request.user, pk)
        serializer = SeriesCollaboratorReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = services_series_collaboration.invite_collaborators(
            series, actor=request.user, slugs=serializer.validated_data["slugs"]
        )
        return Response(SeriesCollaboratorSerializer(rows, many=True).data)


class EventSeriesCollaborationRemoveView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin event series"], request=None, responses={204: None, **ERRORS})
    def post(self, request, pk):
        venue = rbac.scope_by_visibility_or_action(
            request.user, rbac.Action.MANAGE_EVENTS,
            EventSeriesCollaborator.objects.only("id", "series_id"),
            field="series__makerspace_id",
        )
        row = get_object_or_404(
            EventSeriesCollaborator.objects.only("id", "series_id").filter(
                Q(pk__in=venue.values("pk")) | organizer_series_q(request.user, prefix="series__")
            ).distinct(), pk=pk,
        )
        manageable_series(request.user, row.series_id)
        services_series_collaboration.remove_collaborator(pk, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EventSeriesCollaborationInboxView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin event series"], request=None, responses={200: SeriesCollaborationInboxSerializer(many=True), **ERRORS})
    def get(self, request, makerspace_id):
        space = _collaborator_space(request.user, makerspace_id)
        rows = rbac.scope_by_action(
            request.user, rbac.Action.MANAGE_EVENTS,
            servable_queryset(EventSeriesCollaborator.objects.filter(
                makerspace=space, series__makerspace__enabled_modules__contains=["events"]
            ), relation="series__makerspace").select_related("series__makerspace"),
            field="makerspace_id",
        ).order_by("-created_at", "-pk")
        return Response(SeriesCollaborationInboxSerializer(rows, many=True).data)


class EventSeriesCollaborationRespondView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin event series"], request=SeriesCollaborationRespondSerializer, responses={200: SeriesCollaboratorSerializer, **ERRORS})
    def post(self, request, pk):
        row = _manageable_invitation(request.user, pk)
        serializer = SeriesCollaborationRespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services_series_collaboration.respond(
            row, actor=request.user, accept=serializer.validated_data["accept"]
        )
        return Response(SeriesCollaboratorSerializer(row).data)
