from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_member_memberships import (
    AdminMembershipSerializer,
    MembershipCapabilitiesSerializer,
)
from apps.admin_api.views_roles import ERRORS
from apps.makerspaces import membership_services
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import MakerspaceMembership


def _membership_for_manager(actor, pk):
    queryset = rbac.scope_by_action(
        actor,
        rbac.Action.MANAGE_MAKERSPACE,
        MakerspaceMembership.objects.select_related("makerspace", "user", "assigned_role"),
        field="makerspace_id",
    )
    return get_object_or_404(queryset, pk=pk)


def _membership_for_verifier(actor, pk):
    manager_scope = rbac.scope_by_action(
        actor,
        rbac.Action.MANAGE_MAKERSPACE,
        MakerspaceMembership.objects.all(),
        field="makerspace_id",
    ).values("makerspace_id")
    delegate_scope = MakerspaceMembership.objects.filter(
        user=actor, status="active", can_verify=True, makerspace__archived_at__isnull=True
    ).values("makerspace_id")
    return get_object_or_404(
        MakerspaceMembership.objects.select_related("makerspace", "user", "assigned_role").filter(
            Q(makerspace_id__in=manager_scope) | Q(makerspace_id__in=delegate_scope)
        ),
        pk=pk,
    )


class AdminMembershipCapabilitiesView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], request=MembershipCapabilitiesSerializer, responses={200: AdminMembershipSerializer, **ERRORS})
    def patch(self, request, pk):
        membership = _membership_for_manager(request.user, pk)
        serializer = MembershipCapabilitiesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "can_refer" in serializer.validated_data:
            membership = membership_services.set_can_refer(request.user, membership, serializer.validated_data["can_refer"])
        if "can_verify" in serializer.validated_data:
            membership = membership_services.set_can_verify(request.user, membership, serializer.validated_data["can_verify"])
        return Response(AdminMembershipSerializer(membership).data)


class AdminMembershipVerifyView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(request=None, tags=["Admin memberships"], responses={200: AdminMembershipSerializer, **ERRORS})
    def post(self, request, pk):
        membership = _membership_for_verifier(request.user, pk)
        require_module(membership.makerspace, "membership")
        membership = membership_services.verify_member(request.user, membership)
        return Response(AdminMembershipSerializer(membership).data)


class AdminMembershipUnverifyView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(request=None, tags=["Admin memberships"], responses={200: AdminMembershipSerializer, **ERRORS})
    def post(self, request, pk):
        membership = _membership_for_verifier(request.user, pk)
        require_module(membership.makerspace, "membership")
        membership = membership_services.unverify_member(request.user, membership)
        return Response(AdminMembershipSerializer(membership).data)
