"""Superadmin module install/uninstall surface.

**Superadmin only, and that is not an oversight.** `enabled_modules` is superadmin-owned
by existing design -- a staff PATCH carrying it is a hard 403 -- because a module set is
what the operator sells or supports, not what a tenant helps themselves to. This view
gives that owner a real UI instead of the shell, without widening who holds the power.

The Space Manager keeps the surface they already own: `enabled_features`, edited from the
makerspace settings panel.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_groups import deployment_app_status, grouped_module_status
from apps.makerspaces.module_install import (
    ModuleInstallError,
    install_module,
    uninstall_module,
)
from apps.makerspaces.module_profiles import PROFILES

class ModuleActionSerializer(serializers.Serializer):
    """The one field either mutation takes.

    A real class rather than `inline_serializer`, which returns an *instance* and so
    cannot be called with `data=` at request time.
    """

    key = serializers.CharField()


def _makerspace(makerspace_id):
    # Archived spaces are excluded everywhere but /control/, and installing a module on
    # one would be a change nobody can see the effect of.
    return get_object_or_404(Makerspace, pk=makerspace_id, archived_at__isnull=True)


class ModuleGroupListView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(
        tags=["Platform"],
        summary="List module groups and their install state for a makerspace",
        responses={200: OpenApiResponse(description="Grouped module status.")},
    )
    def get(self, request, makerspace_id):
        makerspace = _makerspace(makerspace_id)
        return Response(
            {
                "groups": grouped_module_status(makerspace),
                "deployment": deployment_app_status(),
                "profiles": [
                    {"key": key, "description": description}
                    for key, description in sorted(PROFILES.items())
                ],
            }
        )


class ModuleInstallView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(
        tags=["Platform"],
        summary="Install a module and everything it requires",
        request=ModuleActionSerializer,
        responses={
            200: OpenApiResponse(description="Keys newly installed."),
            400: OpenApiResponse(description="Unknown module, or not shipped by this deployment."),
        },
    )
    def post(self, request, makerspace_id):
        makerspace = _makerspace(makerspace_id)
        serializer = ModuleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            added = install_module(makerspace, serializer.validated_data["key"], actor=request.user)
        except ModuleInstallError as exc:
            # 400 with the service's own message: it already explains *why* (unknown key,
            # tombstoned app, required by another module), and rewording it here would
            # give the operator less than the CLI does.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"installed": added, "groups": grouped_module_status(makerspace)})


class ModuleUninstallView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(
        tags=["Platform"],
        summary="Uninstall a module, keeping its data",
        description=(
            "Clears the capability key only. Rows, uploads and history are retained and "
            "reinstalling restores every surface. Destroying the data is a separate, "
            "irreversible step (`purge_module_data`) that is deliberately CLI-only."
        ),
        request=ModuleActionSerializer,
        responses={
            200: OpenApiResponse(description="Keys uninstalled."),
            400: OpenApiResponse(description="Core module, or required by an installed module."),
        },
    )
    def post(self, request, makerspace_id):
        makerspace = _makerspace(makerspace_id)
        serializer = ModuleActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            removed = uninstall_module(makerspace, serializer.validated_data["key"], actor=request.user)
        except ModuleInstallError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"uninstalled": removed, "groups": grouped_module_status(makerspace)})
