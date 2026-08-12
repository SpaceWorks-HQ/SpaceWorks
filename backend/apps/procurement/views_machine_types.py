from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.machines.models import MachineType
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.procurement.serializers import ToBuyMachineTypeOptionsSerializer
from apps.procurement import access
from apps.procurement.views_common import KIND_PARAM, MODULE_KEY, PROCUREMENT_ERROR_RESPONSES


@extend_schema(tags=["Procurement"])
class ToBuyMachineTypeOptionsView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        summary="List machine types available for a new to-buy item",
        parameters=[KIND_PARAM],
        responses={
            200: ToBuyMachineTypeOptionsSerializer,
            **PROCUREMENT_ERROR_RESPONSES,
        },
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        # Scoped like every other makerspace lookup, so an archived or hard-hidden space
        # is a 404 rather than a 403 that confirms it exists.
        makerspace = get_object_or_404(
            rbac.scope_by_makerspace(
                request.user, Makerspace.objects.all(), makerspace_field="id"
            ),
            pk=makerspace_id,
        )
        require_module(makerspace, MODULE_KEY)
        if not access.can_use(request.user, makerspace_id):
            raise PermissionDenied()
        requested_kind = request.query_params.get("kind")
        rows = access.scope_machine_type_options(
            MachineType.objects.all(),
            request.user,
            makerspace_id,
            requested_kind,
        ).order_by("name", "id")
        return Response(
            ToBuyMachineTypeOptionsSerializer(
                {
                    "machine_type_required": access.machine_type_is_required(
                        request.user, makerspace_id, requested_kind
                    ),
                    "results": rows,
                }
            ).data
        )
