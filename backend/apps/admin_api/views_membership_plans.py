"""Staff surfaces for membership plans and the terms held under them.

All four views are `MANAGE_MAKERSPACE` surfaces scoped through `rbac.scope_by_action`,
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
from apps.admin_api.serializers_membership_plans import (
    MembershipPlanSerializer,
    MembershipTermCreateSerializer,
    MembershipTermSerializer,
)
from apps.admin_api.views_member_memberships import _makerspace as manageable_makerspace
from apps.audit import services as audit
from apps.makerspaces.guards import require_module
from apps.makerspaces.membership_plan_services import cancel_term, create_term
from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm

_MANAGE = rbac.Action.MANAGE_MAKERSPACE
INVALID = OpenApiResponse(description="Invalid input.")


def _gated_makerspace(actor, makerspace_id):
    return require_module(manageable_makerspace(actor, makerspace_id), "membership")


def _scoped(actor, queryset, field="makerspace_id"):
    return rbac.scope_by_action(actor, _MANAGE, queryset, field=field)


class MembershipPlanListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        summary="List membership plans",
        responses={200: MembershipPlanSerializer(many=True)},
    )
    def get(self, request, makerspace_id):
        makerspace = _gated_makerspace(request.user, makerspace_id)
        rows = MembershipPlan.objects.filter(makerspace=makerspace).order_by("name", "pk")
        return Response(MembershipPlanSerializer(rows, many=True).data)

    @extend_schema(
        tags=["Admin memberships"],
        summary="Create a membership plan",
        request=MembershipPlanSerializer,
        responses={201: MembershipPlanSerializer, 400: INVALID},
    )
    def post(self, request, makerspace_id):
        makerspace = _gated_makerspace(request.user, makerspace_id)
        serializer = MembershipPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                row = MembershipPlan.objects.create(
                    makerspace=makerspace, **serializer.validated_data
                )
        except IntegrityError as exc:
            raise ValidationError({"name": "A plan with this name already exists."}) from exc
        audit.record(
            request.user,
            "membership_plan.created",
            makerspace=makerspace,
            target=row,
            meta={"plan_id": row.pk, "name": row.name},
        )
        return Response(MembershipPlanSerializer(row).data, status=status.HTTP_201_CREATED)


class MembershipPlanDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        summary="Update a membership plan",
        request=MembershipPlanSerializer,
        responses={200: MembershipPlanSerializer, 400: INVALID},
    )
    def patch(self, request, pk):
        row = get_object_or_404(
            _scoped(request.user, MembershipPlan.objects.select_related("makerspace")), pk=pk
        )
        makerspace = _gated_makerspace(request.user, row.makerspace_id)
        serializer = MembershipPlanSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                row = serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"name": "A plan with this name already exists."}) from exc
        audit.record(
            request.user,
            "membership_plan.updated",
            makerspace=makerspace,
            target=row,
            meta={"plan_id": row.pk, "fields": sorted(serializer.validated_data)},
        )
        return Response(MembershipPlanSerializer(row).data)


class MembershipTermListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    def _membership(self, actor, pk):
        membership = get_object_or_404(
            _scoped(actor, MakerspaceMembership.objects.select_related("makerspace")), pk=pk
        )
        return membership, _gated_makerspace(actor, membership.makerspace_id)

    @extend_schema(
        tags=["Admin memberships"],
        summary="List the terms of a membership",
        responses={200: MembershipTermSerializer(many=True)},
    )
    def get(self, request, pk):
        membership, _ = self._membership(request.user, pk)
        rows = membership.terms.select_related("plan").order_by("-starts_at", "-pk")
        return Response(MembershipTermSerializer(rows, many=True).data)

    @extend_schema(
        tags=["Admin memberships"],
        summary="Open a term for a membership",
        request=MembershipTermCreateSerializer,
        responses={201: MembershipTermSerializer, 400: INVALID},
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
        tags=["Admin memberships"],
        summary="Cancel an active term",
        request=None,
        responses={200: MembershipTermSerializer, 400: INVALID},
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
