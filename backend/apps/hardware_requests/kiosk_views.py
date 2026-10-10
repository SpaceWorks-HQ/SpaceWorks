"""Kiosk Station work-package, evidence-prepare and online-command routes (phase 9b).

Each route requires a normally authenticated User, the path-bound Station cookie with
the exact-origin/CSRF check, and the ``X-Kiosk-Operator-Lease`` header naming a lease
of that same User. Authority is re-checked on every call; capability-off answers 400,
missing authority 403. The tenant always comes from the Station token.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.evidence.responses import storage_unavailable_response
from apps.evidence.serializers import EvidenceUrlResponseSerializer
from apps.evidence.services_upload import issue_upload
from apps.evidence.storage import StorageUnavailable
from apps.hardware_requests import kiosk_online_commands as online
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.kiosk_command_policy import (
    EVIDENCE_PREPARE,
    OPERATIONS,
    capabilities_live,
    operation_permitted,
)
from apps.hardware_requests.kiosk_serializers import (
    KioskEvidencePrepareSerializer,
    KioskOnlineCommandResultSerializer,
    KioskOnlineCommandSerializer,
    KioskWorkPackageRequestSerializer,
    KioskWorkPackageSerializer,
)
from apps.makerspaces import station_operator_leases as leases
from apps.makerspaces.kiosk_station_throttles import KioskStationSessionThrottle
from apps.makerspaces.station_views_public import LEASE_HEADER_PARAM, live_session, no_store
from apps.tenant_migration.gate_runtime import assert_write_allowed


ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid payload or capability disabled."),
    401: OpenApiResponse(ErrorSerializer, description="Operator is not signed in."),
    403: OpenApiResponse(ErrorSerializer, description="Invalid Station session, lease or authority."),
    404: OpenApiResponse(ErrorSerializer, description="Target not found in this makerspace."),
    429: OpenApiResponse(ErrorSerializer, description="Request rate limit exceeded."),
}
TAGS = ["Kiosk stations"]
WORK_PACKAGE_OPERATIONS = {
    "reviewed_request": ("assign_box", "reviewed_issue", "reviewed_return"),
    "direct_loan": ("direct_return",),
    "direct_handout": ("direct_handout",),
}


def _authorize(request, public_token, operations):
    """Return (station, lease) when ANY of ``operations`` is live for this lease."""
    station, credential, session_id, _expires = live_session(request, public_token)
    assert_write_allowed(station.makerspace_id)
    lease = leases.resolve_lease(
        request.headers.get(leases.LEASE_HEADER), station=station,
        credential=credential, session_id=session_id, user=request.user,
    )
    if not any(capabilities_live(station.makerspace, op) for op in operations):
        raise ValidationError({"feature": "This kiosk operation is disabled for this makerspace."})
    actions = leases.current_actions(lease, request.user, station)
    if not any(
        operation_permitted(station.makerspace, station.kind, op, actions)
        for op in operations
    ):
        raise PermissionDenied(leases.LEASE_REFUSAL)
    return station, lease


class _KioskView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [KioskStationSessionThrottle]


class KioskWorkPackageView(_KioskView):
    @extend_schema(tags=TAGS, summary="Load the minimal work package for one handover",
                   request=KioskWorkPackageRequestSerializer, parameters=[LEASE_HEADER_PARAM],
                   responses={200: KioskWorkPackageSerializer, **ERRORS})
    def post(self, request, public_token, *args, **kwargs):
        serializer = KioskWorkPackageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kind = serializer.validated_data["kind"]
        operations = [OPERATIONS[name] for name in WORK_PACKAGE_OPERATIONS[kind]]
        station, lease = _authorize(request, public_token, operations)
        data = online.work_package(
            station=station, lease=lease, user=request.user,
            kind=kind, pk=serializer.validated_data["id"],
        )
        return no_store(Response(KioskWorkPackageSerializer(data).data))


class KioskEvidencePrepareView(_KioskView):
    @extend_schema(tags=TAGS, summary="Presign a direct-to-staging evidence upload",
                   request=KioskEvidencePrepareSerializer, parameters=[LEASE_HEADER_PARAM],
                   responses={201: EvidenceUrlResponseSerializer, **ERRORS,
                              503: OpenApiResponse(ErrorSerializer, description="Storage unavailable.")})
    def post(self, request, public_token, *args, **kwargs):
        serializer = KioskEvidencePrepareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        station, lease = _authorize(request, public_token, [EVIDENCE_PREPARE])
        try:
            _photo, data = issue_upload(
                station.makerspace, actor=request.user,
                audit_action="kiosk.evidence_upload_issued",
                audit_meta=online.channel_meta(lease, "evidence_prepare"),
                **serializer.validated_data,
            )
        except StorageUnavailable:
            return storage_unavailable_response()
        body = EvidenceUrlResponseSerializer(data).data
        return no_store(Response(body, status=status.HTTP_201_CREATED))


class KioskOnlineCommandView(_KioskView):
    @extend_schema(tags=TAGS, summary="Run one online kiosk command through the workflow",
                   request=KioskOnlineCommandSerializer, parameters=[LEASE_HEADER_PARAM],
                   responses={200: KioskOnlineCommandResultSerializer, **ERRORS,
                              503: OpenApiResponse(ErrorSerializer, description="Storage unavailable.")})
    def post(self, request, public_token, *args, **kwargs):
        serializer = KioskOnlineCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kind = serializer.validated_data["kind"]
        station, lease = _authorize(request, public_token, [OPERATIONS[kind]])
        result = online.execute(
            station=station, lease=lease, user=request.user,
            kind=kind, payload=serializer.validated_data["payload"],
        )
        return no_store(Response({"kind": kind, "result": result}))
