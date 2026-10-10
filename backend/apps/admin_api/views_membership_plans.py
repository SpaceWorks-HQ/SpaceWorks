"""Staff surfaces for membership plans and the terms held under them.

Plan reads and term assignment require `MANAGE_MEMBERS`; plan edits require
`MANAGE_MAKERSPACE`. These surfaces are scoped through `rbac.scope_by_action`,
so a manager of another makerspace sees 404, never 403, and every one of them is gated
by the `membership` module -- plans are community-membership behaviour (A7).
"""
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.views_roles import ERRORS
from apps.admin_api.serializers_membership_plans import (
    MembershipPlanSerializer,
    MembershipTermCreateSerializer,
    MembershipTermSerializer,
)
from apps.admin_api.views_member_memberships import _makerspace as manageable_makerspace
from apps.audit import services as audit
from apps.makerspaces.guards import require_module, require_module_locked
from apps.makerspaces.membership_plan_services import cancel_term, create_term
from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm

_MANAGE = rbac.Action.MANAGE_MEMBERS
INVALID = OpenApiResponse(description="Invalid input.")


def _gated_makerspace(actor, makerspace_id, action=_MANAGE):
    return require_module(manageable_makerspace(actor, makerspace_id, action), "membership")


def _scoped(actor, queryset, field="makerspace_id"):
    return rbac.scope_by_action(actor, _MANAGE, queryset, field=field)


class MembershipPlanListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"], description="Requires manage_members in this makerspace. Staff role administration and membership plan definitions require manage_makerspace.",
        summary="List membership plans",
        responses={200: MembershipPlanSerializer(many=True), **ERRORS},
    )
    def get(self, request, makerspace_id):
        makerspace = _gated_makerspace(request.user, makerspace_id)
        rows = MembershipPlan.objects.filter(makerspace=makerspace).order_by("name", "pk")
        return Response(MembershipPlanSerializer(rows, many=True).data)

    @extend_schema(
        tags=["Admin memberships"], description="Requires manage_makerspace in this makerspace; manage_members alone cannot change plan definitions or prices.",
        summary="Create a membership plan",
        request=MembershipPlanSerializer,
        responses={201: MembershipPlanSerializer, 400: INVALID, **ERRORS},
    )
    def post(self, request, makerspace_id):
        makerspace = _gated_makerspace(request.user, makerspace_id, rbac.Action.MANAGE_MAKERSPACE)
        serializer = MembershipPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                makerspace = require_module_locked(makerspace, "membership")
                row = MembershipPlan.objects.create(
                    makerspace=makerspace, **serializer.validated_data
                )
                audit.record(request.user, "membership_plan.created", makerspace=makerspace,
                             target=row, meta={"plan_id": row.pk, "name": row.name})
        except IntegrityError as exc:
            raise ValidationError({"name": "A plan with this name already exists."}) from exc
        return Response(MembershipPlanSerializer(row).data, status=status.HTTP_201_CREATED)


class MembershipPlanDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"], description="Requires manage_makerspace in this makerspace; manage_members alone cannot change plan definitions or prices.",
        summary="Update a membership plan",
        request=MembershipPlanSerializer,
        responses={200: MembershipPlanSerializer, 400: INVALID, **ERRORS},
    )
    def patch(self, request, pk):
        row = get_object_or_404(
            rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE,
                                 MembershipPlan.objects.select_related("makerspace")), pk=pk
        )
        makerspace = _gated_makerspace(request.user, row.makerspace_id, rbac.Action.MANAGE_MAKERSPACE)
        serializer = MembershipPlanSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                makerspace = require_module_locked(makerspace, "membership")
                row = serializer.save()
                audit.record(request.user, "membership_plan.updated", makerspace=makerspace,
                             target=row, meta={"plan_id": row.pk, "fields": sorted(serializer.validated_data)})
        except IntegrityError as exc:
            raise ValidationError({"name": "A plan with this name already exists."}) from exc
        return Response(MembershipPlanSerializer(row).data)


class MembershipTermListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    def _membership(self, actor, pk):
        membership = get_object_or_404(
            _scoped(actor, MakerspaceMembership.objects.select_related("makerspace")), pk=pk
        )
        return membership, _gated_makerspace(actor, membership.makerspace_id)

    @extend_schema(
        tags=["Admin memberships"], description="Requires manage_members in this makerspace. Staff role administration and membership plan definitions require manage_makerspace.",
        summary="List the terms of a membership",
        responses={200: MembershipTermSerializer(many=True), **ERRORS},
    )
    def get(self, request, pk):
        membership, _ = self._membership(request.user, pk)
        rows = membership.terms.select_related("plan").order_by("-starts_at", "-pk")
        return Response(MembershipTermSerializer(rows, many=True).data)

    @extend_schema(
        tags=["Admin memberships"], description="Requires manage_members in this makerspace. Staff role administration and membership plan definitions require manage_makerspace.",
        summary="Open a term for a membership",
        request=MembershipTermCreateSerializer,
        responses={201: MembershipTermSerializer, 400: INVALID, **ERRORS},
    )
    def post(self, request, pk):
        membership, makerspace = self._membership(request.user, pk)
        serializer = MembershipTermCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = get_object_or_404(
            MembershipPlan.objects.filter(makerspace=makerspace),
            pk=serializer.validated_data["plan_id"],
        )
        term = create_term(
            request.user, membership, plan, starts_at=serializer.validated_data.get("starts_at")
        )
        term = MembershipTerm.objects.select_related("plan").get(pk=term.pk)
        return Response(MembershipTermSerializer(term).data, status=status.HTTP_201_CREATED)


class MembershipTermCancelView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"], description="Requires manage_members in this makerspace. Staff role administration and membership plan definitions require manage_makerspace.",
        summary="Cancel an active term",
        request=None,
        responses={200: MembershipTermSerializer, 400: INVALID, **ERRORS},
    )
    def post(self, request, pk):
        term = get_object_or_404(
            _scoped(
                request.user,
                MembershipTerm.objects.select_related("membership__makerspace", "plan"),
                field="membership__makerspace_id",
            ),
            pk=pk,
        )
        _gated_makerspace(request.user, term.membership.makerspace_id)
        term = cancel_term(request.user, term)
        term = MembershipTerm.objects.select_related("plan").get(pk=term.pk)
        return Response(MembershipTermSerializer(term).data)
