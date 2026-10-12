from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_memberships import (
    MembershipCreateSerializer,
    MembershipListSerializer,
    MembershipRoleAssignSerializer,
)
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.admin_api.services_staff import attach_staff_membership
from apps.admin_api.views_roles import ERRORS, _makerspace
from apps.admin_api.views_member_memberships import _makerspace as member_makerspace
from apps.audit import services as audit
from apps.makerspaces import role_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.payments.models import Payment


class MembershipListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        description="Requires manage_members in this makerspace. Staff creation and role administration require manage_makerspace.",
        responses={200: MembershipListSerializer(many=True), **ERRORS},
    )
    def get(self, request, makerspace_id):
        makerspace = member_makerspace(request.user, makerspace_id)
        memberships = (
            MakerspaceMembership.objects.filter(makerspace=makerspace)
            .select_related("user", "makerspace", "assigned_role")
            .order_by("user__username")
        )
        memberships = list(memberships)
        context = scoped_payment_context(
            request.user,
            rbac.Action.VIEW_FINANCE,
            Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            [membership.pk for membership in memberships],
        )
        return Response(
            MembershipListSerializer(
                memberships,
                many=True,
                context=context,
            ).data
        )

    @extend_schema(
        tags=["Admin memberships"],
        request=MembershipCreateSerializer,
        responses={201: MembershipListSerializer, **ERRORS},
    )
    def post(self, request, makerspace_id):
        makerspace = _makerspace(request.user, makerspace_id)
        serializer = MembershipCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        role = get_object_or_404(
            MakerspaceRole.objects.filter(makerspace=makerspace), pk=data["role_id"]
        )
        with transaction.atomic():
            # Lock the makerspace row FIRST — before can_assign_role locks the actor's
            # membership — so this path shares the makerspace-first lock order used by the
            # role edit/assign services. Otherwise a concurrent create + role edit by the
            # same manager acquires (actor-membership, makerspace) vs (makerspace,
            # actor-membership) and deadlocks (P2).
            makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
            role_services.can_assign_role(request.user, makerspace, role)
            membership, created, is_break_glass = attach_staff_membership(
                actor=request.user,
                makerspace=makerspace,
                role=role,
                username=data["username"],
                email=data.get("email", ""),
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                password=data.get("password", ""),
            )
            audit.record(
                request.user,
                (
                    "superadmin.break_glass_space_manager_created"
                    if is_break_glass
                    else "staff.created" if created else "staff.membership_updated"
                ),
                makerspace=makerspace,
                target=membership.user,
                meta={"role_id": role.id, "role_slug": role.slug},
            )
        membership = (
            MakerspaceMembership.objects.select_related("user", "makerspace", "assigned_role")
            .get(pk=membership.pk)
        )
        context = scoped_payment_context(
            request.user,
            rbac.Action.VIEW_FINANCE,
            Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            [membership.pk],
        )
        return Response(
            MembershipListSerializer(membership, context=context).data,
            status=status.HTTP_201_CREATED,
        )


class MembershipRoleAssignView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        request=MembershipRoleAssignSerializer,
        responses={200: MembershipListSerializer, **ERRORS},
    )
    def patch(self, request, makerspace_id, membership_id):
        makerspace = _makerspace(request.user, makerspace_id)
        membership = get_object_or_404(
            MakerspaceMembership.objects.filter(makerspace=makerspace), pk=membership_id
        )
        serializer = MembershipRoleAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = get_object_or_404(
            MakerspaceRole.objects.filter(makerspace=makerspace),
            pk=serializer.validated_data["role_id"],
        )
        membership = role_services.assign_role(
            makerspace=makerspace,
            actor=request.user,
            membership=membership,
            role=role,
        )
        membership = (
            MakerspaceMembership.objects.select_related("user", "makerspace", "assigned_role")
            .get(pk=membership.pk)
        )
        context = scoped_payment_context(
            request.user,
            rbac.Action.VIEW_FINANCE,
            Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            [membership.pk],
        )
        return Response(MembershipListSerializer(membership, context=context).data)
