from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.rbac import Action
from apps.admin_api.machine_access import resolve_machine
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.machines import role_scope
from apps.machines.models import Machine
from apps.machines.serializers import MachinePublicitySerializer
from apps.machines.serializers_public_machines import PublicMachineSerializer
from apps.makerspaces.guards import require_module


class MachinePublicityView(APIView):
    permission_classes = [IsActiveStaff]

    def _resolve(self, user, pk):
        machine = resolve_machine(user, pk)
        # Publishing a machine to the public catalogue is machine administration, so it
        # follows the role's machine scope rather than the bare makerspace-wide grant.
        if not rbac.can(user, Action.MANAGE_MACHINES, machine.makerspace_id) or not (
            role_scope.covers_machine(user, machine)
        ):
            raise PermissionDenied()
        require_module(machine.makerspace_id, 'machines')
        return machine

    @extend_schema(
        tags=['Admin machines'],
        summary='Preview a machine public listing',
        request=None,
        responses={200: PublicMachineSerializer},
    )
    def get(self, request, pk, *args, **kwargs):
        machine = self._resolve(request.user, pk)
        return Response(PublicMachineSerializer(machine).data)

    @extend_schema(
        tags=['Admin machines'],
        summary='Set machine public visibility',
        request=MachinePublicitySerializer,
        responses={
            200: PublicMachineSerializer,
            400: OpenApiResponse(description='Invalid publicity setting.'),
            403: OpenApiResponse(description='MANAGE_MACHINES is required.'),
            404: OpenApiResponse(description='Machine not found.'),
        },
    )
    def patch(self, request, pk, *args, **kwargs):
        machine = self._resolve(request.user, pk)
        serializer = MachinePublicitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_public = serializer.validated_data['is_public']
        with transaction.atomic():
            machine = Machine.objects.select_for_update().get(pk=machine.pk)
            if machine.is_public != is_public:
                previous = machine.is_public
                machine.is_public = is_public
                machine.save(update_fields=['is_public', 'updated_at'])
                audit.record(
                    request.user,
                    'machine.publicity_changed',
                    makerspace=machine.makerspace,
                    target=machine,
                    meta={'from': previous, 'to': is_public},
                )
        return Response(PublicMachineSerializer(machine).data)
