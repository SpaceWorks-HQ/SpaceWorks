from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.makerspaces.servability import servable_queryset
from apps.machines import role_scope
from apps.operations.views_dashboard_counts import DashboardSerializer, build_dashboard


@extend_schema(
    tags=["Dashboard"],
    summary="Staff operations dashboard counts",
    request=None,
    responses={
        200: DashboardSerializer,
        403: OpenApiResponse(description="Permission denied."),
        404: OpenApiResponse(description="Makerspace not found."),
    },
)
class DashboardView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "head", "options"]

    def get(self, request, makerspace_id):
        makerspace = get_object_or_404(
            rbac.scope_by_makerspace(
                request.user,
                servable_queryset(),
                makerspace_field="id",
            ),
            pk=makerspace_id,
        )
        if _is_guest_only(request.user, makerspace.id):
            raise PermissionDenied()
        if not (
            rbac.can(request.user, rbac.Action.VIEW_INVENTORY, makerspace.id)
            or rbac.can(request.user, rbac.Action.MANAGE_PRINTING, makerspace.id)
            or rbac.can(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id)
        ):
            raise PermissionDenied()
        manages_machines = rbac.can(
            request.user, rbac.Action.MANAGE_MACHINES, makerspace.id
        )
        machine_scope = (
            role_scope.manage_scope_for(request.user, makerspace.id)
            if manages_machines
            else role_scope.EXEMPT
        )
        # Shared with the notification inbox, which hides for exactly this actor -- see
        # `role_scope.is_machine_only` for why holding MANAGE_MACHINES is not the question.
        machine_only = role_scope.is_machine_only(request.user, makerspace.id)
        return Response(
            build_dashboard(
                makerspace,
                machine_scope=machine_scope,
                machine_only=machine_only,
                direct_collect=role_scope.role_grants_directly(
                    request.user,
                    makerspace.id,
                    rbac.Action.COLLECT_SERVICE_REQUEST,
                ),
                include_pending_payments=rbac.can(
                    request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id
                ),
            )
        )


def _is_guest_only(user, makerspace_id):
    return rbac.is_handout_only(user, makerspace_id)
