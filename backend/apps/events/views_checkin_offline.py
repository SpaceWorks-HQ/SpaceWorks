from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.events.models import EventCheckInEvent
from apps.events.serializers_checkin_offline import (
    OfflineCheckInSyncRequestSerializer,
    OfflineCheckInSyncResponseSerializer,
    OfflineRosterResponseSerializer,
)
from apps.events.services_checkin_roster import issue_roster
from apps.events.services_checkin_sync import synchronize, validated_lease
from apps.events.throttles import EventOfflineRosterThrottle, EventOfflineSyncThrottle
from apps.events.views_admin import _manageable_event
from apps.hardware_requests.exceptions import ErrorSerializer


ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Feature disabled or invalid batch."),
    401: OpenApiResponse(ErrorSerializer, description="Authentication or lease failed."),
    403: OpenApiResponse(ErrorSerializer, description="Event authority changed."),
    404: OpenApiResponse(ErrorSerializer, description="Event not found."),
    409: OpenApiResponse(ErrorSerializer, description="Roster window closed."),
    410: OpenApiResponse(ErrorSerializer, description="Synchronization deadline passed."),
    413: OpenApiResponse(ErrorSerializer, description="Roster exceeds the offline limit."),
    429: OpenApiResponse(ErrorSerializer, description="Request rate limit exceeded."),
}


class EventOfflineRosterView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_classes = [EventOfflineRosterThrottle]

    @extend_schema(
        tags=["Admin events"],
        summary="Download a minimal expiring offline check-in roster",
        request=None,
        responses={200: OfflineRosterResponseSerializer, **ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        payload = issue_roster(
            _manageable_event(request.user, pk),
            actor=request.user,
            kind="staff",
        )
        response = Response(OfflineRosterResponseSerializer(payload).data)
        response["Cache-Control"] = "private, no-store"
        return response


class EventOfflineSyncView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_classes = [EventOfflineSyncThrottle]

    @extend_schema(
        tags=["Admin events"],
        summary="Synchronize queued offline event check-ins",
        request=OfflineCheckInSyncRequestSerializer,
        responses={200: OfflineCheckInSyncResponseSerializer, **ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        serializer = OfflineCheckInSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lease = validated_lease(
            serializer.validated_data["lease_token"],
            event,
            kind="staff",
            actor=request.user,
        )
        payload = synchronize(
            event,
            serializer.validated_data["operations"],
            lease=lease,
            actor=request.user,
            source=EventCheckInEvent.Source.OFFLINE_SYNC,
            session_id=lease["lease_id"],
        )
        response = Response(OfflineCheckInSyncResponseSerializer(payload).data)
        response["Cache-Control"] = "private, no-store"
        return response
