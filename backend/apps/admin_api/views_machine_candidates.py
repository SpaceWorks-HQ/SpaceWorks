from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.admin_api.machine_access import resolve_machine
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_machine_candidates import OperatorCandidateSerializer
from apps.machines import access
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import MakerspaceMembership


class MachineOperatorCandidatesView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin machines'],
        summary='List active members eligible for machine operator assignment',
        request=None,
        responses={
            200: OperatorCandidateSerializer(many=True),
            403: OpenApiResponse(description='Operator delegation is not permitted.'),
            404: OpenApiResponse(description='Machine not found.'),
        },
    )
    def get(self, request, pk, *args, **kwargs):
        machine = resolve_machine(request.user, pk)
        if not access.can_delegate_operators(request.user, machine):
            raise PermissionDenied()
        require_module(machine.makerspace_id, 'machines')
        memberships = (
            MakerspaceMembership.objects.filter(
                makerspace_id=machine.makerspace_id,
                status="active",
                user__is_active=True,
                user__access_status=User.AccessStatus.ACTIVE,
            )
            .select_related('user')
            .order_by('user__username', 'user_id')
        )
        return Response(OperatorCandidateSerializer(memberships, many=True).data)
