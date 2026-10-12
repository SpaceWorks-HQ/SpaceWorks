"""Station/lease-only replay HTTP boundary; never accepts image bytes."""

import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import APIException, ParseError, PermissionDenied, Throttled, UnsupportedMediaType, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.evidence.storage import StorageUnavailable
from apps.backup.not_restored import TenantNotRestored
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.replay_authorization import authenticate
from apps.hardware_requests.replay_execute import execute
from apps.hardware_requests.replay_failures import ReplayFailure
from apps.hardware_requests.replay_prepare import prepare
from apps.hardware_requests.replay_serializers import ReplayEnvelopeSerializer, ReplayResultSerializer
from apps.hardware_requests.replay_throttles import (
    ReplayExecuteThrottle, ReplayPrepareThrottle, ReplayExecuteIpThrottle, ReplayPrepareIpThrottle,
)
from apps.makerspaces.kiosk_station_services import observed_station
from apps.makerspaces.station_auth import KioskStationCookieAuthentication
from apps.makerspaces.station_views_public import LEASE_HEADER_PARAM, no_store
from apps.tenant_migration.gate_runtime import assert_write_allowed, boundary_tenant_write
from apps.tenant_migration.gate_errors import SourceMigrationGateError

logger = logging.getLogger(__name__)

ERRORS = {code: OpenApiResponse(ErrorSerializer, description=detail) for code, detail in (
    (400, "Invalid command, target, module or feature disabled."),
    (403, "Station, origin, session, operator lease or live permission refused."),
    (409, "Ownership conflict, expired command, predecessor refusal or concurrent claim."),
    (423, "Tenant migration source gate is closed."),
    (429, "Replay rate limit exceeded."), (503, "Storage or replay temporarily unavailable."),
)}
PARAMETERS = [LEASE_HEADER_PARAM, OpenApiParameter("X-Station-CSRF", str, OpenApiParameter.HEADER, required=True)]


class _ReplayView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [KioskStationCookieAuthentication]
    parser_classes = [JSONParser]

    def handle_exception(self, exc):
        if isinstance(exc, (SourceMigrationGateError, TenantNotRestored)):
            return super().handle_exception(exc)
        if isinstance(exc, Throttled):
            exc = ReplayFailure("rate_limited")
        elif isinstance(exc, (ParseError, UnsupportedMediaType)):
            exc = ReplayFailure("invalid_command")
        elif not isinstance(exc, (ReplayFailure, APIException, StorageUnavailable)):
            logger.error("kiosk_replay_boundary_failure", extra={"error_type": type(exc).__name__})
            exc = ReplayFailure("server_unavailable")
        if isinstance(exc, (ReplayFailure, StorageUnavailable, ValidationError, PermissionDenied)):
            if isinstance(exc, StorageUnavailable):
                exc = ReplayFailure("storage_unavailable")
            elif isinstance(exc, ValidationError):
                exc = ReplayFailure("invalid_command")
            elif isinstance(exc, PermissionDenied):
                exc = ReplayFailure("session_mismatch")
            return no_store(Response({"code": exc.code, "detail": exc.detail}, status=exc.status))
        return super().handle_exception(exc)


class KioskReplayPrepareView(_ReplayView):
    permission_classes = [AllowAny]
    throttle_classes = [ReplayPrepareThrottle, ReplayPrepareIpThrottle]

    @extend_schema(tags=["Kiosk stations"], summary="Prepare an ordered command and staging evidence upload",
                   description="Requires the path-bound Station cookie, exact Origin/Referer, X-Station-CSRF and signed human lease; no browser login required. Send the identical envelope to execute.",
                   request=ReplayEnvelopeSerializer, parameters=PARAMETERS,
                   responses={200: ReplayResultSerializer, **ERRORS})
    def post(self, request, public_token, *args, **kwargs):
        station = observed_station(public_token)
        if station is None:
            raise ReplayFailure("station_revoked")
        with boundary_tenant_write(station.makerspace_id):
            assert_write_allowed(station.makerspace_id)
            identity = authenticate(request, station, public_token)
            serializer = ReplayEnvelopeSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return no_store(Response(ReplayResultSerializer(prepare(identity, serializer.validated_data)).data))


class KioskReplayExecuteView(_ReplayView):
    permission_classes = [AllowAny]
    throttle_classes = [ReplayExecuteThrottle, ReplayExecuteIpThrottle]

    @extend_schema(tags=["Kiosk stations"], summary="Execute or recover one prepared handover command",
                   description="Same Station cookie, origin/CSRF and human lease as prepare. Current authority and domain rules are checked again; duplicate success returns stable references.",
                   request=ReplayEnvelopeSerializer, parameters=PARAMETERS,
                   responses={200: ReplayResultSerializer, **ERRORS})
    def post(self, request, public_token, client_command_id, *args, **kwargs):
        station = observed_station(public_token)
        if station is None:
            raise ReplayFailure("station_revoked")
        with boundary_tenant_write(station.makerspace_id):
            assert_write_allowed(station.makerspace_id)
            identity = authenticate(request, station, public_token)
            serializer = ReplayEnvelopeSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            envelope = serializer.validated_data
            if envelope["client_command_id"] != client_command_id:
                raise ReplayFailure("idempotency_conflict")
            return no_store(Response(ReplayResultSerializer(execute(identity, envelope)).data))
