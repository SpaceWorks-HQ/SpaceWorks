from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.servability import servable_queryset
from apps.presence import services
from apps.presence.serializers import (
    PresenceCurrentSerializer,
    PresenceRosterSerializer,
    PresenceSessionSerializer,
    PresenceStartSerializer,
)
from apps.apiclients.throttling import MemberPrincipalRateThrottle


ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid input."),
    401: OpenApiResponse(description="Authentication required."),
    403: OpenApiResponse(ErrorSerializer, description="Membership permission required."),
    404: OpenApiResponse(description="Makerspace not found."),
    429: OpenApiResponse(description="Rate limit exceeded."),
}


class PresenceStartView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "presence_start"

    @extend_schema(tags=["Presence"], request=PresenceStartSerializer, responses={201: PresenceSessionSerializer, **ERRORS})
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        serializer = PresenceStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.start_session(
            request.user, makerspace, serializer.validated_data["duration_minutes"],
            latitude=serializer.validated_data.get("latitude"), longitude=serializer.validated_data.get("longitude"),
            accuracy=serializer.validated_data.get("accuracy"),
        )
        return Response(PresenceSessionSerializer(session).data, status=201)


class PresenceCurrentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Presence"], request=None, responses={200: PresenceCurrentSerializer, **ERRORS})
    def get(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        session = services.current_session(request.user, makerspace)
        return Response(PresenceCurrentSerializer({"active": bool(session), "session": session}).data)


class PresenceEndView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Presence"], request=None, responses={200: PresenceCurrentSerializer, **ERRORS})
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        services.end_session(request.user, makerspace)
        return Response({"active": False, "session": None})


class PresenceRosterView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin makerspaces"], request=None, responses={200: PresenceRosterSerializer(many=True), **ERRORS})
    def get(self, request, makerspace_id):
        get_object_or_404(servable_queryset(), pk=makerspace_id)
        if not rbac.can(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        from django.utils import timezone
        from apps.presence.models import PresenceSession
        sessions = PresenceSession.objects.filter(
            makerspace_id=makerspace_id, ended_at__isnull=True, expires_at__gt=timezone.now()
        ).select_related("member", "membership__assigned_role").order_by("started_at", "id")
        return Response(PresenceRosterSerializer(sessions, many=True).data)
