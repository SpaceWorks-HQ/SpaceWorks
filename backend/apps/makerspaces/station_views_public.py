"""Kiosk Station PIN session (AllowAny) and the authenticated operator lease.

Every cookie-accepting route enforces the exact Origin/Referer plus X-Station-CSRF
check, refuses uniformly, and answers no-store. The tenant is always resolved from the
Station token; a request body never names a makerspace.
"""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.kiosk_command_policy import permitted_operations
from apps.makerspaces import kiosk_station_services as services
from apps.makerspaces import station_operator_leases as leases
from apps.makerspaces.kiosk_station_throttles import (
    KioskOperatorLeaseThrottle,
    KioskStationPinIpThrottle,
    KioskStationPinTokenThrottle,
    KioskStationSessionThrottle,
)
from apps.makerspaces.platform import makerspace_public_origins
from apps.makerspaces.station_auth import KioskStationCookieAuthentication
from apps.makerspaces.station_security import assert_exact_origin
from apps.makerspaces.station_serializers import (
    KioskOperatorLeaseSerializer,
    KioskStationBootstrapSerializer,
    KioskStationPinSerializer,
)
from apps.tenant_migration.gate_runtime import assert_write_allowed


GENERIC_ERROR = OpenApiResponse(
    ErrorSerializer,
    description="Invalid Station credential, session, origin, feature or lease.",
)
TAGS = ["Kiosk stations"]
LEASE_HEADER_PARAM = OpenApiParameter(
    "X-Kiosk-Operator-Lease", str, OpenApiParameter.HEADER, required=True,
    description="Signed operator lease returned by the operator-lease route.",
)


def assert_station_csrf(request, station):
    assert_exact_origin(
        request,
        allowed_origins=lambda: (
            makerspace_public_origins(station.makerspace)
            | set(settings.CORS_ALLOWED_ORIGINS)
        ),
        refusal=services.STATION_REFUSAL,
    )


def no_store(response):
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    return response


def live_session(request, public_token):
    """Resolve the cookie, then the exact-origin check, uniformly refused."""
    try:
        resolved = services.resolve_session(
            public_token, request.COOKIES.get(services.COOKIE_NAME, ""),
        )
        assert_station_csrf(request, resolved[0])
    except (APIException, DjangoValidationError):
        raise PermissionDenied(services.STATION_REFUSAL) from None
    return resolved


class KioskStationSessionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [KioskStationPinTokenThrottle, KioskStationPinIpThrottle]

    @extend_schema(
        tags=TAGS, summary="Exchange a kiosk Station PIN for a Station session",
        auth=[], request=KioskStationPinSerializer,
        responses={201: KioskStationBootstrapSerializer, 400: GENERIC_ERROR,
                   403: GENERIC_ERROR, 429: GENERIC_ERROR},
    )
    def post(self, request, public_token, *args, **kwargs):
        serializer = KioskStationPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        observed = services.observed_station(public_token)
        if observed is None:
            raise PermissionDenied(services.STATION_REFUSAL)
        assert_station_csrf(request, observed)
        # Anonymous but tenant state: a closed source gate refuses a new session.
        assert_write_allowed(observed.makerspace_id)
        slug = serializer.validated_data.get("makerspace_slug")
        if slug is not None and slug != observed.makerspace.slug:
            raise PermissionDenied(services.STATION_REFUSAL)
        if not permitted_operations(observed.makerspace, observed.kind):
            raise PermissionDenied(services.STATION_REFUSAL)
        try:
            station, credential, _sid, cookie, expires_at = services.start_session(
                public_token, pin=serializer.validated_data["pin"],
            )
        except (APIException, DjangoValidationError):
            raise PermissionDenied(services.STATION_REFUSAL) from None
        makerspace = station.makerspace
        body = KioskStationBootstrapSerializer({
            "station": {"id": station.pk, "name": station.name, "kind": station.kind},
            "makerspace": {"id": makerspace.pk, "slug": makerspace.slug, "name": makerspace.name},
            "session_expires_at": expires_at,
            "permitted_operations": permitted_operations(makerspace, station.kind),
        }).data
        response = Response(body, status=status.HTTP_201_CREATED)
        response.set_cookie(
            services.COOKIE_NAME, cookie,
            max_age=max(0, int((expires_at - timezone.now()).total_seconds())),
            httponly=True, secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            path=services.cookie_path(credential.public_token),
        )
        return no_store(response)

    @extend_schema(
        tags=TAGS, summary="End the Station session and revoke its operator leases",
        auth=[{"KioskStationCookie": []}], request=None,
        responses={204: None, 403: GENERIC_ERROR, 429: GENERIC_ERROR},
    )
    def delete(self, request, public_token, *args, **kwargs):
        station, _credential, session_id, expires_at = live_session(request, public_token)
        assert_write_allowed(station.makerspace_id)
        services.end_session(station, session_id=session_id, expires_at=expires_at)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(services.COOKIE_NAME, path=services.cookie_path(public_token))
        return no_store(response)


class KioskOperatorLeaseView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [KioskOperatorLeaseThrottle, KioskStationSessionThrottle]

    @extend_schema(
        tags=TAGS, summary="Issue a human operator lease on this Station session",
        request=None,
        responses={201: KioskOperatorLeaseSerializer, 401: GENERIC_ERROR,
                   403: GENERIC_ERROR, 429: GENERIC_ERROR},
    )
    def post(self, request, public_token, *args, **kwargs):
        station, credential, session_id, expires_at = live_session(request, public_token)
        assert_write_allowed(station.makerspace_id)
        lease, token = leases.issue_lease(
            station=station, credential=credential, session_id=session_id,
            session_expires_at=expires_at, user=request.user,
        )
        body = KioskOperatorLeaseSerializer({
            "lease_token": token, "lease_id": lease.pk, "expires_at": lease.expires_at,
            "allowed_actions": lease.allowed_actions,
            "permitted_operations": permitted_operations(
                station.makerspace, station.kind, lease.allowed_actions
            ),
        }).data
        return no_store(Response(body, status=status.HTTP_201_CREATED))

    @extend_schema(
        tags=TAGS, summary="Revoke the caller's operator lease (operator sign-out)",
        request=None, parameters=[LEASE_HEADER_PARAM],
        responses={204: None, 401: GENERIC_ERROR, 403: GENERIC_ERROR},
    )
    def delete(self, request, public_token, *args, **kwargs):
        station, credential, session_id, _expires = live_session(request, public_token)
        assert_write_allowed(station.makerspace_id)
        lease = leases.resolve_lease(
            request.headers.get(leases.LEASE_HEADER), station=station,
            credential=credential, session_id=session_id, user=request.user,
        )
        leases.revoke_lease(lease, user=request.user)
        return no_store(Response(status=status.HTTP_204_NO_CONTENT))


# Referenced so the cookie scheme appears in the schema for kiosk command routes.
__all__ = ["KioskStationCookieAuthentication", "live_session", "assert_station_csrf"]
