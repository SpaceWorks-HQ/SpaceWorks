"""Staff surfaces for certification types and the grants issued against them.

Authority is per MACHINE TYPE, not per makerspace: a role scoped to the lasers must not
be able to declare who is trained on the printers. `access.can_create_machine` is the
type-level predicate (`MANAGE_MACHINES` narrowed to a linked type, or the type's own
direct manager), and the SAME predicate filters the list — a row that lists and then 403s
on click is the failure mode `docs/INVARIANTS.md` calls out under Machine scoping.
"""

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_certifications import (
    CertificationGrantCreateSerializer,
    CertificationGrantRevokeSerializer,
    CertificationGrantSerializer,
    CertificationTypeSerializer,
    CertificationTypeUpdateSerializer,
)
from apps.audit import services as audit
from apps.machines import access
from apps.machines.models import CertificationGrant, CertificationType, MachineType
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import MakerspaceMembership


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
        responses={200: CertificationTypeSerializer(many=True)},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        require_module(makerspace_id, "machines")
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
            400: OpenApiResponse(description="Invalid certification type."),
            403: OpenApiResponse(description="Machine type authority required."),
        },
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = require_module(makerspace_id, "machines")
        serializer = CertificationTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        machine_type = get_object_or_404(
            MachineType.objects.filter(
                pk=serializer.validated_data["machine_type"].pk
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
            400: OpenApiResponse(description="Invalid certification type."),
            403: OpenApiResponse(description="Machine type authority required."),
        },
    )
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
            403: OpenApiResponse(description="Machine type authority required."),
        },
    )
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


class CertificationGrantListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machines"],
        summary="List grants for a certification type",
        request=None,
        responses={200: CertificationGrantSerializer(many=True)},
    )
    def get(self, request, pk, *args, **kwargs):
        row = _resolved_type(request.user, pk)
        grants = (
            CertificationGrant.objects.filter(certification_type=row)
            .select_related("membership__user")
            .order_by("-granted_at", "-pk")
        )
        return Response(CertificationGrantSerializer(grants, many=True).data)

    @extend_schema(
        tags=["Admin machines"],
        summary="Grant a certification to a membership",
        request=CertificationGrantCreateSerializer,
        responses={
            201: CertificationGrantSerializer,
            400: OpenApiResponse(description="Invalid grant."),
            403: OpenApiResponse(description="Machine type authority required."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        row = _resolved_type(request.user, pk)
        serializer = CertificationGrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        membership = MakerspaceMembership.objects.filter(
            pk=data["membership_id"], makerspace_id=row.makerspace_id
        ).first()
        if membership is None:
            # A membership in another makerspace is "unknown" here, never a 403 that
            # confirms it exists elsewhere.
            raise ValidationError({"membership_id": "Unknown membership."})
        expires_at = data.get("expires_at")
        if expires_at is None and row.validity_days:
            expires_at = timezone.now() + timedelta(days=row.validity_days)
        grant = CertificationGrant.objects.create(
            certification_type=row,
            membership=membership,
            granted_by=request.user,
            expires_at=expires_at,
            notes=data.get("notes", ""),
        )
        audit.record(
            request.user,
            "certification.granted",
            makerspace=row.makerspace,
            target=grant,
            meta={
                "certification_type_id": row.pk,
                "membership_id": membership.pk,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
        return Response(
            CertificationGrantSerializer(grant).data, status=status.HTTP_201_CREATED
        )


class CertificationGrantRevokeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machines"],
        summary="Revoke a certification grant",
        request=CertificationGrantRevokeSerializer,
        responses={
            200: CertificationGrantSerializer,
            400: OpenApiResponse(description="Already revoked."),
            403: OpenApiResponse(description="Machine type authority required."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        grant = get_object_or_404(
            CertificationGrant.objects.select_related(
                "certification_type__makerspace",
                "certification_type__machine_type",
                "membership__user",
            ).filter(
                certification_type__in=_scoped_types(request.user).values("pk")
            ),
            pk=pk,
        )
        certification_type = grant.certification_type
        require_module(certification_type.makerspace, "machines")
        if not access.can_create_machine(
            request.user,
            certification_type.makerspace_id,
            certification_type.machine_type,
        ):
            raise PermissionDenied()
        if grant.revoked_at is not None:
            raise ValidationError("This certification is already revoked.")
        serializer = CertificationGrantRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant.revoked_at = timezone.now()
        grant.revoked_by = request.user
        notes = serializer.validated_data.get("notes", "")
        if notes:
            grant.notes = notes
        grant.save(update_fields=["revoked_at", "revoked_by", "notes"])
        audit.record(
            request.user,
            "certification.revoked",
            makerspace=certification_type.makerspace,
            target=grant,
            meta={
                "certification_type_id": certification_type.pk,
                "membership_id": grant.membership_id,
                "notes": notes,
            },
        )
        return Response(CertificationGrantSerializer(grant).data)
