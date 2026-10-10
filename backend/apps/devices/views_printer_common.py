from drf_spectacular.utils import OpenApiResponse
from rest_framework.views import APIView

from apps.devices.authentication import DeviceAuthentication
from apps.devices.errors import DeviceErrorSerializer
from apps.devices.permissions import DeviceRoutePermission

PRINTER_ERRORS = {
    code: OpenApiResponse(DeviceErrorSerializer, description=description)
    for code, description in [(400, "Invalid payload or adapter module disabled."),
        (401, "Authentication/signature/replay refused."), (403, "Authority or device revoked."),
        (404, "Target outside scope or absent."), (409, "Conflicting command/report."),
        (410, "Delivery lease expired."), (423, "Tenant frozen for migration.")]
}


class SignedDeviceView(APIView):
    authentication_classes = [DeviceAuthentication]
    permission_classes = [DeviceRoutePermission]
