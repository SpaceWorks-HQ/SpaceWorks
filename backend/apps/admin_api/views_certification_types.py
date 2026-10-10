"""Staff surfaces for certification types and the grants issued against them.

Authority is per MACHINE TYPE, not per makerspace: a role scoped to the lasers must not
be able to declare who is trained on the printers. `access.can_create_machine` is the
type-level predicate (`MANAGE_MACHINES` narrowed to a linked type, or the type's own
direct manager), and the SAME predicate filters the list — a row that lists and then 403s
on click is the failure mode `docs/INVARIANTS.md` calls out under Machine scoping.
"""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_certifications import (
    CertificationTypeSerializer,
    CertificationTypeUpdateSerializer,
)
from apps.audit import services as audit
from apps.machines import access
from apps.machines.models import CertificationType, MachineType
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.openapi_errors import errors


def _scoped_makerspace(user, pk):
    return get_object_or_404(
        rbac.scope_by_makerspace(user, Makerspace.objects.all(), makerspace_field="id"),
        pk=pk,
    )


def _scoped_types(user):
    """Certification types inside the actor's tenant scope. Type authority is separate."""
    return rbac.scope_by_makerspace(
        user, CertificationType.objects.select_related("makerspace", "machine_type")
    )


def _resolved_type(user, pk):
    row = get_object_or_404(_scoped_types(user), pk=pk)
    require_module(row.makerspace, "machines")
    if not access.can_create_machine(user, row.makerspace_id, row.machine_type):
        raise PermissionDenied()
    return row


class CertificationTypeListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machines"],
        summary="List certification types in a makerspace",
        request=None,
        responses={200: CertificationTypeSerializer(many=True), **errors(400, 401, 403, 404)},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        require_module(_scoped_makerspace(request.user, makerspace_id), "machines")
        if not access.can_see_machines(request.user, makerspace_id):
            raise PermissionDenied()
        rows = [
            row
            for row in _scoped_types(request.user)
            .filter(makerspace_id=makerspace_id)
            .order_by("machine_type__name", "name", "pk")
            # Same predicate as the mutation gate, deliberately per-row: the set of
            # certification types in a lab is small, and agreeing exactly with the
            # object check matters more here than saving a query.
            if access.can_create_machine(request.user, makerspace_id, row.machine_type)
        ]
        return Response(CertificationTypeSerializer(rows, many=True).data)

    @extend_schema(
        tags=["Admin machines"],
        summary="Create a certification type",
        request=CertificationTypeSerializer,
        responses={
            201: CertificationTypeSerializer,
            **errors(400, 401, 403, 404),
            423: OpenApiResponse(description="Makerspace frozen for tenant migration."),
        },
    )
    @transaction.atomic
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = require_module(_scoped_makerspace(request.user, makerspace_id), "machines")
        serializer = CertificationTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        machine_type = get_object_or_404(
            MachineType.objects.filter(
                Q(makerspace__isnull=True) | Q(pk__in=rbac.scope_by_makerspace(
                    request.user, MachineType.objects.all()
                ).values("pk")),
                pk=serializer.validated_data["machine_type"].pk,
            ),
        )
        if machine_type.makerspace_id not in (None, makerspace_id):
            raise ValidationError({"machine_type": "Unknown machine type."})
        if not access.can_create_machine(request.user, makerspace_id, machine_type):
            raise PermissionDenied()
        row = CertificationType.objects.create(
            makerspace=makerspace, **serializer.validated_data
        )
        audit.record(
            request.user,
            "certification_type.created",
            makerspace=makerspace,
            target=row,
            meta={"machine_type_id": machine_type.pk, "name": row.name},
        )
        return Response(
            CertificationTypeSerializer(row).data, status=status.HTTP_201_CREATED
        )


class CertificationTypeDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machines"],
        summary="Update a certification type",
        request=CertificationTypeUpdateSerializer,
        responses={
            200: CertificationTypeSerializer,
            **errors(400, 401, 403, 404),
            423: OpenApiResponse(description="Makerspace frozen for tenant migration."),
        },
    )
    @transaction.atomic
    def patch(self, request, pk, *args, **kwargs):
        row = _resolved_type(request.user, pk)
        serializer = CertificationTypeUpdateSerializer(
            row, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        row = serializer.save()
        audit.record(
            request.user,
            "certification_type.updated",
            makerspace=row.makerspace,
            target=row,
            meta={"fields": sorted(serializer.validated_data.keys())},
        )
        return Response(CertificationTypeSerializer(row).data)

    @extend_schema(
        tags=["Admin machines"],
        summary="Deactivate a certification type",
        request=None,
        responses={
            200: CertificationTypeSerializer,
            **errors(400, 401, 403, 404),
            423: OpenApiResponse(description="Makerspace frozen for tenant migration."),
        },
    )
    @transaction.atomic
    def delete(self, request, pk, *args, **kwargs):
        # Soft-delete. Issued grants are evidence that a member was trained on a date;
        # deleting the type would cascade them away and erase that trail.
        row = _resolved_type(request.user, pk)
        if row.is_active:
            row.is_active = False
            row.save(update_fields=["is_active", "updated_at"])
        audit.record(
            request.user,
            "certification_type.deactivated",
            makerspace=row.makerspace,
            target=row,
            meta={"name": row.name},
        )
        return Response(CertificationTypeSerializer(row).data)

