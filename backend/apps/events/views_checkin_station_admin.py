from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.events.serializers_admin import EmptyActionSerializer
from apps.events.serializers_station import (
    StationRevealResponseSerializer,
    StationRevealSerializer,
    StationRotationSerializer,
    StationStatusSerializer,
)
from apps.events.services_station import disable, reveal, rotate, station_url, status_payload
from apps.events.throttles import EventStationRevealThrottle
from apps.events.views_admin import _manageable_event
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_feature


ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Feature disabled or invalid request."),
    403: OpenApiResponse(ErrorSerializer, description="Event access or step-up denied."),
    404: OpenApiResponse(ErrorSerializer, description="Event not found."),
    409: OpenApiResponse(ErrorSerializer, description="Rotate the PIN instead of revealing."),
    429: OpenApiResponse(ErrorSerializer, description="Request rate limit exceeded."),
    503: OpenApiResponse(ErrorSerializer, description="Credential secrets are unavailable."),
}


def _credential_response(serializer_class, payload):
    response = Response(serializer_class(payload).data)
    response["Cache-Control"] = "private, no-store"
    return response


class EventStationStatusView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"],
        summary="Read venue-station configuration without revealing its PIN",
        request=None,
        responses={200: StationStatusSerializer, **ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        require_feature(event.makerspace, "events.offline_checkin")
        return _credential_response(StationStatusSerializer, status_payload(event))

    @extend_schema(
        tags=["Admin events"],
        summary="Disable a venue check-in station",
        request=None,
        responses={200: StationStatusSerializer, **ERRORS},
    )
    def delete(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        credential = disable(event, actor=request.user)
        return _credential_response(
            StationStatusSerializer,
            status_payload(event, credential),
        )


class EventStationRotateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"],
        summary="Create or rotate an event-scoped eight-digit station PIN",
        request=EmptyActionSerializer,
        responses={200: StationRotationSerializer, **ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        serializer = EmptyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential, pin = rotate(event, actor=request.user)
        payload = {
            "pin": pin,
            "public_token": credential.public_token,
            "version": credential.version,
            "station_url": station_url(event, credential.public_token),
        }
        return _credential_response(StationRotationSerializer, payload)


class EventStationRevealView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_classes = [EventStationRevealThrottle]

    @extend_schema(
        tags=["Admin events"],
        summary="Reveal the current station PIN after password step-up",
        request=StationRevealSerializer,
        responses={200: StationRevealResponseSerializer, **ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        serializer = StationRevealSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential, pin = reveal(
            event,
            actor=request.user,
            current_password=serializer.validated_data["current_password"],
        )
        return _credential_response(
            StationRevealResponseSerializer,
            {"pin": pin, "version": credential.version},
        )
