"""Admin lifecycle for kiosk scanner/handover Stations (MANAGE_MAKERSPACE scoped)."""

from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces import kiosk_station_services as services
from apps.makerspaces.guards import require_feature
from apps.makerspaces.kiosk_station_throttles import KioskStationRevealThrottle
from apps.makerspaces.models import Makerspace
from apps.makerspaces.models_stations import Station, StationCredential
from apps.makerspaces.station_serializers import (
    KioskStationCreateSerializer,
    KioskStationRevealResponseSerializer,
    KioskStationRevealSerializer,
    KioskStationSecretSerializer,
    KioskStationSerializer,
)


ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Feature disabled or invalid request."),
    403: OpenApiResponse(ErrorSerializer, description="Makerspace access or step-up denied."),
    404: OpenApiResponse(ErrorSerializer, description="Station not found."),
    409: OpenApiResponse(ErrorSerializer, description="Rotate the PIN instead of revealing."),
    429: OpenApiResponse(ErrorSerializer, description="Request rate limit exceeded."),
    503: OpenApiResponse(ErrorSerializer, description="Credential secrets are unavailable."),
}
TAGS = ["Admin kiosk stations"]


def station_url(makerspace, public_token):
    token = quote(str(public_token))
    if makerspace.frontend_domain and makerspace.frontend_domain_status == "verified":
        return f"https://{makerspace.frontend_domain}/kiosk/{token}"
    base = (settings.PUBLIC_APP_BASE_URL or "http://localhost:5000").rstrip("/")
    return f"{base}/m/{quote(makerspace.slug)}/kiosk/{token}"


def _payload(station, credential=None, pin=None):
    if credential is None:
        credential = StationCredential.objects.filter(station=station).first()
    data = {
        "id": station.pk, "name": station.name, "kind": station.kind,
        "enabled": bool(credential and credential.is_enabled),
        "public_token": credential.public_token if credential else None,
        "version": credential.version if credential else None,
        "station_url": (
            station_url(station.makerspace, credential.public_token) if credential else None
        ),
        "rotated_at": credential.rotated_at if credential else None,
        "created_at": station.created_at,
    }
    if pin is not None:
        data["pin"] = pin
    return data


def _no_store(response):
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    return response


def _managed_makerspace(user, makerspace_id):
    makerspace = get_object_or_404(Makerspace, pk=makerspace_id)
    require_action(user, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk)
    require_feature(makerspace, services.KIOSK_FEATURE)
    return makerspace


def _managed_station(user, pk):
    station = get_object_or_404(
        Station.objects.select_related("makerspace"), pk=pk, kind__in=services.KIOSK_KINDS,
    )
    require_action(user, rbac.Action.MANAGE_MAKERSPACE, station.makerspace_id)
    require_feature(station.makerspace, services.KIOSK_FEATURE)
    return station


class KioskStationListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=TAGS, summary="List kiosk Stations", request=None,
                   responses={200: KioskStationSerializer(many=True), **ERRORS})
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _managed_makerspace(request.user, makerspace_id)
        stations = Station.objects.filter(
            makerspace=makerspace, kind__in=services.KIOSK_KINDS
        ).select_related("makerspace").order_by("pk")[:200]
        rows = [_payload(station) for station in stations]
        return _no_store(Response(KioskStationSerializer(rows, many=True).data))

    @extend_schema(tags=TAGS, summary="Create a kiosk Station and its first PIN",
                   request=KioskStationCreateSerializer,
                   responses={201: KioskStationSecretSerializer, **ERRORS})
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = _managed_makerspace(request.user, makerspace_id)
        serializer = KioskStationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        station, credential, pin = services.create_station(
            makerspace, actor=request.user, **serializer.validated_data,
        )
        data = KioskStationSecretSerializer(_payload(station, credential, pin)).data
        return _no_store(Response(data, status=status.HTTP_201_CREATED))


class KioskStationDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=TAGS, summary="Read one kiosk Station without its PIN",
                   request=None, responses={200: KioskStationSerializer, **ERRORS})
    def get(self, request, pk, *args, **kwargs):
        station = _managed_station(request.user, pk)
        return _no_store(Response(KioskStationSerializer(_payload(station)).data))

    @extend_schema(tags=TAGS, summary="Disable a kiosk Station and revoke its leases",
                   request=None, responses={200: KioskStationSerializer, **ERRORS})
    def delete(self, request, pk, *args, **kwargs):
        station = _managed_station(request.user, pk)
        credential = services.disable(station, actor=request.user)
        return _no_store(Response(KioskStationSerializer(_payload(station, credential)).data))


class KioskStationRotateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=TAGS, summary="Rotate a kiosk Station PIN (re-enables it)",
                   request=None, responses={200: KioskStationSecretSerializer, **ERRORS})
    def post(self, request, pk, *args, **kwargs):
        station = _managed_station(request.user, pk)
        credential, pin = services.rotate(station, actor=request.user)
        data = KioskStationSecretSerializer(_payload(station, credential, pin)).data
        return _no_store(Response(data))


class KioskStationRevealView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_classes = [KioskStationRevealThrottle]

    @extend_schema(tags=TAGS, summary="Reveal a kiosk Station PIN after password step-up",
                   request=KioskStationRevealSerializer,
                   responses={200: KioskStationRevealResponseSerializer, **ERRORS})
    def post(self, request, pk, *args, **kwargs):
        station = _managed_station(request.user, pk)
        serializer = KioskStationRevealSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential, pin = services.reveal(
            station, actor=request.user,
            current_password=serializer.validated_data["current_password"],
        )
        data = KioskStationRevealResponseSerializer(
            {"pin": pin, "version": credential.version}
        ).data
        return _no_store(Response(data))
