from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, IsActiveSuperAdmin
from apps.admin_api.serializers_platform_monitoring import (
    MakerspaceUsageSerializer, PlatformDashboardSerializer, PlatformProblemsSerializer,
)
from apps.makerspaces.servability import servable_queryset
from apps.makerspaces.usage_snapshot import usage_snapshot
from apps.openapi_errors import errors
from apps.operations.platform_dashboard import build_platform_dashboard
from apps.operations.platform_problems import run_problem_checks


class PlatformDashboardView(APIView):
    permission_classes = [IsActiveSuperAdmin]
    http_method_names = ["get", "head", "options"]

    @extend_schema(tags=["Platform"], summary="Read platform operations dashboard", request=None,
                   responses={200: PlatformDashboardSerializer, **errors(400, 401, 403)})
    def get(self, request):
        return Response(PlatformDashboardSerializer(build_platform_dashboard(request.user)).data)


class PlatformProblemsView(APIView):
    permission_classes = [IsActiveSuperAdmin]
    http_method_names = ["get", "head", "options"]

    @extend_schema(tags=["Platform"], summary="Run read-only platform problem checks on demand", request=None,
                   responses={200: PlatformProblemsSerializer, **errors(400, 401, 403)})
    def get(self, request):
        return Response(PlatformProblemsSerializer(run_problem_checks(request.user)).data)


class MakerspaceUsageView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "head", "options"]

    @extend_schema(tags=["Admin makerspaces"], summary="Read own makerspace usage and effective limits", request=None,
                   responses={200: MakerspaceUsageSerializer, **errors(400, 401, 403, 404)})
    def get(self, request, makerspace_id):
        space = get_object_or_404(rbac.scope_by_visibility_or_action(
            request.user, rbac.Action.MANAGE_MAKERSPACE, servable_queryset(), field="id",
        ), pk=makerspace_id)
        if not rbac.can(request.user, rbac.Action.MANAGE_MAKERSPACE, space.pk):
            raise PermissionDenied("Not allowed to manage this makerspace.")
        return Response(MakerspaceUsageSerializer(usage_snapshot(space)).data)
