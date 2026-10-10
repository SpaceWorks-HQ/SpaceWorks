"""Certification grant endpoints, split from type administration."""

from datetime import timedelta

from django.db import transaction
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
    CertificationGrantCreateSerializer, CertificationGrantRevokeSerializer,
    CertificationGrantSerializer,
)
from apps.audit import services as audit
from apps.machines import access
from apps.machines.models import CertificationGrant
from apps.machines.notifications_certifications import notify_certification
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import MakerspaceMembership
from apps.openapi_errors import errors
from .views_certification_types import _resolved_type


def _scoped_grants(user):
    return rbac.scope_by_makerspace(
        user, CertificationGrant.objects.all(),
        makerspace_field="certification_type__makerspace_id",
    )

class CertificationGrantListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machines"],
        summary="List grants for a certification type",
        request=None,
        responses={200: CertificationGrantSerializer(many=True), **errors(400, 401, 403, 404)},
    )
    def get(self, request, pk, *args, **kwargs):
        row = _resolved_type(request.user, pk)
        grants = (
            _scoped_grants(request.user).filter(certification_type=row)
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
            **errors(400, 401, 403, 404),
            423: OpenApiResponse(description="Makerspace frozen for tenant migration."),
        },
    )
    @transaction.atomic
    def post(self, request, pk, *args, **kwargs):
        row = _resolved_type(request.user, pk)
        serializer = CertificationGrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        membership = rbac.scope_by_makerspace(
            request.user, MakerspaceMembership.objects.all()
        ).filter(
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
        notify_certification(grant, "granted")
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
            **errors(400, 401, 403, 404),
            423: OpenApiResponse(description="Makerspace frozen for tenant migration."),
        },
    )
    @transaction.atomic
    def post(self, request, pk, *args, **kwargs):
        grant = get_object_or_404(
            # Lock only the grant, avoiding nullable related-user outer joins.
            # A competing revoke must see the committed revoked_at before emitting.
            _scoped_grants(request.user).select_for_update(of=("self",)).select_related(
                "certification_type__makerspace",
                "certification_type__machine_type",
                "membership__user",
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
        notify_certification(grant, "revoked")
        return Response(CertificationGrantSerializer(grant).data)
