from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.devices.serializers_printers import JobSerializer, ResultSerializer, TelemetrySerializer
from apps.devices.services_printer_apply import report_result
from apps.devices.services_printer_reports import telemetry
from apps.devices.views_printer_common import PRINTER_ERRORS, SignedDeviceView


class DevicePrinterTelemetryView(SignedDeviceView):
    @extend_schema(tags=["Device protocol"], request=TelemetrySerializer,
                   responses={200: JobSerializer, **PRINTER_ERRORS})
    def post(self, request, pk):
        return Response(JobSerializer(telemetry(request.user, pk, request.data)).data)


class DevicePrinterResultView(SignedDeviceView):
    @extend_schema(tags=["Device protocol"], request=ResultSerializer,
                   responses={200: JobSerializer, **PRINTER_ERRORS})
    def post(self, request, pk):
        return Response(JobSerializer(report_result(request.user, pk, request.data)).data)
