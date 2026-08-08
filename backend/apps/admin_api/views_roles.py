from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_roles import (
    CapabilitySerializer,
    RoleCreateSerializer,
    RoleMachineScopeSerializer,
    RoleMachineScopeWriteSerializer,
    RoleSerializer,
    RoleWriteSerializer,
    role_queryset,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.machines import role_scope, role_scope_services
from apps.makerspaces import role_services
from apps.makerspaces.models import Makerspace


ERRORS = {400: ErrorSerializer, 401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer, 409: OpenApiResponse(ErrorSerializer)}

_CATALOG = (
    ("Inventory", (("view_inventory", "Inventory and outstanding-loans ledger visibility."), ("edit_inventory", "Catalog, stock, needs-fix, stocktake, asset warranty, procurement, and containers."), ("manage_qr", "QR printing, scanner, and QR management."))),
    ("Requests / Handover", (("accept_request", "Review hardware requests."), ("reject_request", "Reject hardware requests."), ("assign_box", "Assign physical handover boxes."), ("issue_request", "Issue accepted requests."), ("issue_direct_loan", "Create direct loans."), ("return_request", "Process returns."), ("upload_evidence", "Upload required handover evidence."), ("collect_service_request", "Hand finished machine jobs to their requester, without machine management."))),
    ("Machines", (("manage_machines", "Machines, warranty, maintenance, documents, operators, usage, and reports."),)),
    ("Printing", (("manage_printing", "Print queue, printers, materials, warranty, reports, and printer-type machines."),)),
    ("Events", (("manage_events", "Event administration and attendance."),)),
    ("Bookings", (("manage_bookings", "Bookable-space and booking operations."),)),
    ("Reports / Audit", (("view_audit", "Analytics, accountability, audit log, timelines, history, and exports."),)),
    ("Makerspace admin", (("manage_makerspace", "Settings, integrations, role management, and staff delegation."),)),
)


def _makerspace(actor, makerspace_id):
    makerspace = get_object_or_404(rbac.scope_by_makerspace(actor, Makerspace.objects.all(), makerspace_field="id"), pk=makerspace_id)
    if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk):
        raise PermissionDenied()
    return makerspace


def _role(actor, makerspace_id, role_id):
    makerspace = _makerspace(actor, makerspace_id)
    return makerspace, get_object_or_404(role_queryset(), pk=role_id, makerspace=makerspace)


def _catalog(actor, makerspace):
    actor_actions = rbac.effective_actions(actor, makerspace.id)
    superadmin = actor.is_superuser or getattr(actor, "role", None) == "superadmin"
    rows = []
    for group, items in _CATALOG:
        for value, description in items:
            grantable = value in actor_actions and (superadmin or value != rbac.Action.MANAGE_MAKERSPACE)
            reason = None if grantable else (
                "Only a global superadmin may grant makerspace administration." if value == rbac.Action.MANAGE_MAKERSPACE else "You do not currently hold this capability."
            )
            rows.append({"value": value, "label": value.replace("_", " ").title(), "description": description, "group": group, "grantable": grantable, "lock_reason": reason})
    return rows


class RoleListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin roles"], responses={200: RoleSerializer(many=True), **ERRORS})
    def get(self, request, makerspace_id):
        makerspace = _makerspace(request.user, makerspace_id)
        return Response(RoleSerializer(role_queryset().filter(makerspace=makerspace).order_by("name", "id"), many=True).data)

    @extend_schema(tags=["Admin roles"], request=RoleCreateSerializer, responses={201: RoleSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        makerspace = _makerspace(request.user, makerspace_id)
        serializer = RoleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = role_services.create_role(makerspace=makerspace, actor=request.user, **serializer.validated_data)
        return Response(RoleSerializer(role_queryset().get(pk=role.pk)).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin roles"], responses={200: RoleSerializer, **ERRORS})
    def get(self, request, makerspace_id, role_id):
        _, role = _role(request.user, makerspace_id, role_id)
        return Response(RoleSerializer(role).data)

    @extend_schema(tags=["Admin roles"], request=RoleWriteSerializer, responses={200: RoleSerializer, **ERRORS})
    def patch(self, request, makerspace_id, role_id):
        makerspace, role = _role(request.user, makerspace_id, role_id)
        serializer = RoleWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        role = role_services.update_role(makerspace=makerspace, role=role, actor=request.user, **serializer.validated_data)
        return Response(RoleSerializer(role_queryset().get(pk=role.pk)).data)

    @extend_schema(tags=["Admin roles"], responses={204: None, **ERRORS})
    def delete(self, request, makerspace_id, role_id):
        makerspace, role = _role(request.user, makerspace_id, role_id)
        role_services.delete_role(makerspace=makerspace, role=role, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CapabilityCatalogView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin roles"], responses={200: CapabilitySerializer(many=True), **ERRORS})
    def get(self, request, makerspace_id):
        return Response(CapabilitySerializer(_catalog(request.user, _makerspace(request.user, makerspace_id)), many=True).data)


def _machine_scope_payload(makerspace, role):
    """Current links + the full option set, so the console needs one request, not three."""
    granted = role.granted_actions if isinstance(role.granted_actions, list) else []
    exempt = rbac.Action.MANAGE_MAKERSPACE in rbac.expand_implied_actions(
        action for action in granted if isinstance(action, str)
    )
    return {
        **role_scope_services.current_scope(role),
        "available_machine_types": [
            {"id": row.pk, "label": row.name, "is_builtin": row.is_builtin}
            for row in role_scope_services.assignable_machine_types(makerspace)
        ],
        "available_machines": [
            {"id": row.pk, "label": row.name, "is_active": row.is_active}
            for row in role_scope_services.assignable_machines(makerspace)
        ],
        # A role that grants no machine authority at all has nothing to scope either --
        # ticking types for it would imply an access it does not have.
        "scoping_applies": (
            not exempt and rbac.Action.MANAGE_MACHINES in rbac.expand_implied_actions(
                action for action in granted if isinstance(action, str)
            )
        ),
    }


class RoleMachineScopeView(APIView):
    """Which machines a role's MANAGE_MACHINES grant reaches.

    Console parity: machine scoping fails closed, so without this surface a Space Manager
    could create a machine-managing role and have no way to make it able to manage
    anything — the capability would exist only in `/control/` and the shell.
    """

    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin roles"], responses={200: RoleMachineScopeSerializer, **ERRORS})
    def get(self, request, makerspace_id, role_id):
        makerspace, role = _role(request.user, makerspace_id, role_id)
        return Response(RoleMachineScopeSerializer(_machine_scope_payload(makerspace, role)).data)

    @extend_schema(
        tags=["Admin roles"],
        request=RoleMachineScopeWriteSerializer,
        responses={200: RoleMachineScopeSerializer, **ERRORS},
    )
    def put(self, request, makerspace_id, role_id):
        makerspace, role = _role(request.user, makerspace_id, role_id)
        serializer = RoleMachineScopeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role_scope_services.set_role_machine_scope(
            makerspace=makerspace,
            role=role,
            actor=request.user,
            **serializer.validated_data,
        )
        role = role_queryset().get(pk=role.pk)
        return Response(RoleMachineScopeSerializer(_machine_scope_payload(makerspace, role)).data)
