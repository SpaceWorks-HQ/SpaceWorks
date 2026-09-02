from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.events import collaborator_services
from apps.events.exceptions import UseSeriesCollaborators
from apps.events.organizer_authority import organizer_event_q
from apps.events.models import Event, EventCollaborator
from apps.events.serializers_collaborators import (
    EventCollaborationInboxSerializer,
    EventCollaborationRespondSerializer,
    EventCollaboratorReplaceSerializer,
    EventCollaboratorSerializer,
)
from apps.events.views_admin import _manageable_event
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


COLLABORATION_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid collaboration request."),
    403: OpenApiResponse(ErrorSerializer, description="Event management access denied."),
    404: OpenApiResponse(ErrorSerializer, description="Event collaboration not found."),
}


def _collaborator_makerspace(actor, makerspace_id):
    makerspace = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_EVENTS,
            Makerspace.objects.all(),
            field="id",
        ),
        pk=makerspace_id,
    )
    require_module(makerspace, "events")
    if not rbac.can(actor, rbac.Action.MANAGE_EVENTS, makerspace.pk):
        raise PermissionDenied()
    return makerspace


def _manageable_collaboration(actor, pk):
    """The collaborator side of an invitation, for accept and decline.

    Scoped to the COLLABORATOR's makerspace, not the host's -- that is what makes this
    reachable from the collaborator's own custom domain, and it is why the respond route has
    its own `origin_scope_routes` entry rather than sharing one with the host's remove.
    """
    collaborator = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_EVENTS,
            servable_queryset(EventCollaborator.objects.filter(
                # An archived host's invitation must not remain answerable: accepting it
                # would grant eligibility for an event that is invisible everywhere but
                # `/control/`. The read filter alone is not enough -- a partner holding the
                # row id could otherwise still POST to respond. The host's MODULE state
                # matters for the same reason: with `events` off, A's event surfaces are
                # withdrawn, so its invitation must not stay answerable either.
                event__makerspace__enabled_modules__contains=["events"],
            ), relation="event__makerspace").select_related("makerspace", "event__makerspace"),
            field="makerspace_id",
        ),
        pk=pk,
    )
    require_module(collaborator.makerspace, "events")
    if not rbac.can(
        actor,
        rbac.Action.MANAGE_EVENTS,
        collaborator.makerspace_id,
    ):
        raise PermissionDenied()
    return collaborator


class EventCollaboratorListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"],
        summary="List an event's collaborators",
        request=None,
        responses={200: EventCollaboratorSerializer(many=True), **COLLABORATION_ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        collaborators = servable_queryset(EventCollaborator.objects.filter(
            event=event,
            # Archived spaces are invisible outside `/control/`, and this response carries
            # a partner's name and slug.
        ), relation="makerspace").select_related("makerspace").order_by("makerspace__slug", "id")
        return Response(EventCollaboratorSerializer(collaborators, many=True).data)

    @extend_schema(
        tags=["Admin events"],
        summary="Replace an event's collaborators",
        request=EventCollaboratorReplaceSerializer,
        responses={200: EventCollaboratorSerializer(many=True), **COLLABORATION_ERRORS},
    )
    def put(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        if event.series_id:
            raise UseSeriesCollaborators()
        serializer = EventCollaboratorReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collaborators = collaborator_services.invite_collaborators(
            event,
            actor=request.user,
            slugs=serializer.validated_data["slugs"],
        )
        return Response(EventCollaboratorSerializer(collaborators, many=True).data)


class EventCollaborationRemoveView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"],
        summary="Remove an event collaborator",
        request=None,
        responses={204: None, **COLLABORATION_ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        # Admit rows whose EVENT the actor organizes as well as those in venue scope, or an
        # organizer at an unlinked venue 404s here before _manageable_event can apply the
        # exact-event authority -- so it could list and replace collaborators but not
        # remove one.
        venue_scoped = rbac.scope_by_visibility_or_action(
            request.user,
            rbac.Action.MANAGE_EVENTS,
            EventCollaborator.objects.only("id", "event_id"),
            field="event__makerspace_id",
        )
        collaboration = get_object_or_404(
            EventCollaborator.objects.only("id", "event_id")
            .filter(
                Q(pk__in=venue_scoped.values("pk"))
                | organizer_event_q(request.user, event_prefix="event__")
            )
            .distinct(),
            pk=pk,
        )
        if collaboration.source_series_collaboration_id:
            raise UseSeriesCollaborators()
        _manageable_event(request.user, collaboration.event_id)
        collaborator_services.remove_collaborator(pk, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EventCollaborationInboxView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"],
        summary="List collaboration invitations for a makerspace",
        request=None,
        responses={
            200: EventCollaborationInboxSerializer(many=True),
            **COLLABORATION_ERRORS,
        },
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _collaborator_makerspace(request.user, makerspace_id)
        collaborations = rbac.scope_by_action(
            request.user,
            rbac.Action.MANAGE_EVENTS,
            servable_queryset(EventCollaborator.objects.filter(
                makerspace=makerspace,
                # Archiving the HOST -- or its disabling `events` -- does not remove its
                # collaboration rows, and this serializer carries the host's event title
                # and times. Archived is invisible everywhere but `/control/`, and a
                # withdrawn module means those surfaces are gone, so neither may keep
                # appearing in a partner's inbox.
                event__makerspace__enabled_modules__contains=["events"],
            ), relation="event__makerspace").select_related("event__makerspace"),
            field="makerspace_id",
        ).order_by("-created_at", "-id")
        return Response(
            EventCollaborationInboxSerializer(collaborations, many=True).data
        )


class EventCollaborationRespondView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"],
        summary="Accept or decline an event collaboration",
        request=EventCollaborationRespondSerializer,
        responses={200: EventCollaboratorSerializer, **COLLABORATION_ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        collaboration = _manageable_collaboration(request.user, pk)
        serializer = EventCollaborationRespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collaboration = collaborator_services.respond_to_invitation(
            collaboration,
            actor=request.user,
            accept=serializer.validated_data["accept"],
        )
        return Response(EventCollaboratorSerializer(collaboration).data)
