from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.devices import services_commands
from apps.devices.serializers_commands import AckSerializer, CommandAckSerializer, LeaseResponseSerializer
from apps.devices.serializers_printers import StrictSerializer
from apps.devices.views_printer_common import PRINTER_ERRORS, SignedDeviceView


class DeviceCommandLeaseView(SignedDeviceView):
    @extend_schema(tags=["Device protocol"], request=StrictSerializer,
                   responses={200: LeaseResponseSerializer, **PRINTER_ERRORS})
    def post(self, request):
        serializer = StrictSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(LeaseResponseSerializer({"command": services_commands.lease_command(request.user)}).data)


class DeviceCommandAckView(SignedDeviceView):
    @extend_schema(tags=["Device protocol"], request=AckSerializer,
                   responses={200: CommandAckSerializer, **PRINTER_ERRORS})
    def post(self, request, pk):
        serializer = AckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        command = services_commands.acknowledge(request.user, pk, **serializer.validated_data)
        return Response(CommandAckSerializer(command).data)
