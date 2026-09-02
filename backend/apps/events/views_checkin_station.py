from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events.models import EventCheckInEvent, EventCheckInStationCredential
from apps.events.serializers_checkin_offline import (
    OfflineCheckInSyncRequestSerializer,
    OfflineCheckInSyncResponseSerializer,
    OfflineRosterResponseSerializer,
)
from apps.events.serializers_station import StationPinSerializer
from apps.events.services_checkin_roster import issue_roster
from apps.events.services_checkin_sync import synchronize, validated_lease
from apps.events.services_station import (
    STATION_COOKIE_NAME,
    STATION_REFUSAL,
    resolve_session,
    start_session,
)
from apps.events.station_auth import EventStationCookieAuthentication
from apps.events.throttles import (
    EventStationPinIpThrottle,
    EventStationPinTokenThrottle,
    EventStationSessionThrottle,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.platform import makerspace_public_origins


GENERIC_ERROR = OpenApiResponse(
    ErrorSerializer,
    description="Invalid station credential, session, origin, feature, or time window.",
)


def _cookie_path(public_token):
    return f"/api/v1/event-checkin-stations/{public_token}/"


def _assert_station_csrf(request, event):
    if "X-Station-CSRF" not in request.headers:
        raise PermissionDenied(STATION_REFUSAL)
    raw = request.headers.get("Origin") or request.headers.get("Referer", "")
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        raise PermissionDenied(STATION_REFUSAL)
    candidate = f"{parts.scheme}://{parts.netloc}"
    allowed = (
        makerspace_public_origins(event.makerspace)
        | set(settings.CORS_ALLOWED_ORIGINS)
    )
    if candidate not in allowed:
        raise PermissionDenied(STATION_REFUSAL)


def _observed_event(public_token):
    credential = EventCheckInStationCredential.objects.select_related(
        "event__makerspace"
    ).filter(public_token=public_token).first()
    return credential.event if credential is not None else None


class EventStationSessionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [EventStationPinTokenThrottle, EventStationPinIpThrottle]

    @extend_schema(
        tags=["Event check-in stations"],
        summary="Exchange an event-scoped PIN for a station session",
        auth=[],
        request=StationPinSerializer,
        responses={204: None, 400: GENERIC_ERROR, 403: GENERIC_ERROR, 429: GENERIC_ERROR},
    )
    def post(self, request, public_token, *args, **kwargs):
        serializer = StationPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        observed = _observed_event(public_token)
        if observed is None:
            raise PermissionDenied(STATION_REFUSAL)
        _assert_station_csrf(request, observed)
        try:
            event, credential, _session_id, cookie, expires_at = start_session(
                public_token,
                pin=serializer.validated_data["pin"],
            )
        except (APIException, DjangoValidationError):
            raise PermissionDenied(STATION_REFUSAL) from None
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.set_cookie(
            STATION_COOKIE_NAME,
            cookie,
            max_age=max(0, int((expires_at - timezone.now()).total_seconds())),
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            path=_cookie_path(credential.public_token),
        )
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(
        tags=["Event check-in stations"],
        summary="Clear the local station session cookie",
        auth=[{"EventStationCookie": []}],
        request=None,
        responses={204: None, 403: GENERIC_ERROR, 429: GENERIC_ERROR},
    )
    def delete(self, request, public_token, *args, **kwargs):
        try:
            event, _credential, _session_id = resolve_session(
                public_token,
                request.COOKIES.get(STATION_COOKIE_NAME, ""),
            )
            _assert_station_csrf(request, event)
        except (APIException, DjangoValidationError):
            raise PermissionDenied(STATION_REFUSAL) from None
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(
            STATION_COOKIE_NAME,
            path=_cookie_path(public_token),
        )
        response["Cache-Control"] = "private, no-store"
        return response


class _StationCookieView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [EventStationCookieAuthentication]
    throttle_classes = [EventStationSessionThrottle]

    def station_session(self, request, public_token):
        try:
            event, credential, session_id = resolve_session(
                public_token,
                request.COOKIES.get(STATION_COOKIE_NAME, ""),
            )
        except (APIException, DjangoValidationError):
            raise PermissionDenied(STATION_REFUSAL) from None
        _assert_station_csrf(request, event)
        return event, credential, session_id


class EventStationRosterView(_StationCookieView):
    @extend_schema(
        tags=["Event check-in stations"],
        summary="Download the station's minimal expiring attendee roster",
        request=None,
        responses={
            200: OfflineRosterResponseSerializer,
            403: GENERIC_ERROR,
            409: GENERIC_ERROR,
            413: GENERIC_ERROR,
            429: GENERIC_ERROR,
        },
    )
    def get(self, request, public_token, *args, **kwargs):
        event, credential, session_id = self.station_session(request, public_token)
        try:
            payload = issue_roster(
                event,
                actor=None,
                kind="station",
                session_id=session_id,
                station_version=credential.version,
            )
        except ValidationError:
            raise PermissionDenied(STATION_REFUSAL) from None
        response = Response(OfflineRosterResponseSerializer(payload).data)
        response["Cache-Control"] = "private, no-store"
        return response


class EventStationSyncView(_StationCookieView):
    @extend_schema(
        tags=["Event check-in stations"],
        summary="Synchronize queued PIN-station check-ins",
        request=OfflineCheckInSyncRequestSerializer,
        responses={
            200: OfflineCheckInSyncResponseSerializer,
            400: GENERIC_ERROR,
            403: GENERIC_ERROR,
            410: GENERIC_ERROR,
            429: GENERIC_ERROR,
        },
    )
    def post(self, request, public_token, *args, **kwargs):
        event, credential, session_id = self.station_session(request, public_token)
        serializer = OfflineCheckInSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lease = validated_lease(
            serializer.validated_data["lease_token"],
            event,
            kind="station",
            session_id=session_id,
            station_version=credential.version,
        )
        try:
            payload = synchronize(
                event,
                serializer.validated_data["operations"],
                lease=lease,
                actor=None,
                source=EventCheckInEvent.Source.VENUE_STATION,
                session_id=session_id,
                station_version=credential.version,
            )
        except ValidationError:
            raise PermissionDenied(STATION_REFUSAL) from None
        response = Response(OfflineCheckInSyncResponseSerializer(payload).data)
        response["Cache-Control"] = "private, no-store"
        return response
