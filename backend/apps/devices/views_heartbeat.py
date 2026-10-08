"""The signed heartbeat: the one 7a route a device calls with its own key."""

from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.authentication import DeviceAuthentication
from apps.devices.errors import DeviceErrorSerializer
from apps.devices.permissions import DeviceRoutePermission
from apps.devices.serializers_identity import DeviceIdentitySerializer
from apps.devices.services_requests import record_heartbeat


@extend_schema(tags=["Device protocol"])
class DeviceHeartbeatView(APIView):
    authentication_classes = [DeviceAuthentication]
    permission_classes = [DeviceRoutePermission]

    @extend_schema(
        summary="Report that a device is alive (signed device request)",
        request=None,
        responses={
            200: DeviceIdentitySerializer,
            **{
                code: OpenApiResponse(DeviceErrorSerializer, description=text)
                for code, text in (
                    (400, "Module disabled."),
                    (401, "Missing, malformed, stale, replayed or invalid signature."),
                    (403, "Device not allowed on this route, revoked or tenant unavailable."),
                    (423, "Tenant frozen for migration."),
                )
            },
        },
    )
    def post(self, request):
        device = record_heartbeat(request.user, now=timezone.now())
        return Response(DeviceIdentitySerializer(device).data)
