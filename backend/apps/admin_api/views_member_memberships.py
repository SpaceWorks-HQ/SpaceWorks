from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_member_memberships import (AdminMembershipSerializer, InvitationSerializer,
    MembershipRequestSerializer, RevokeSerializer, RoleIdSerializer)
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.admin_api.views_roles import ERRORS
from apps.makerspaces import membership_services, waiver_services
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole, MakerspaceWaiver, MembershipRequest
from apps.makerspaces.serializers_memberships import WaiverPublishSerializer
from apps.payments.models import Payment


class MembershipPagination(PageNumberPagination):
    page_size = 24


def _makerspace(actor, makerspace_id):
    queryset = rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE, Makerspace.objects.filter(archived_at__isnull=True), field="id")
    makerspace = get_object_or_404(queryset, pk=makerspace_id)
    if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.id):
        raise PermissionDenied()
    return makerspace


def _role(makerspace, role_id):
    return get_object_or_404(MakerspaceRole.objects.filter(makerspace=makerspace), pk=role_id)


def _membership_context(actor, membership, **extra):
    return {
        **extra,
        **scoped_payment_context(
            actor,
            rbac.Action.MANAGE_MAKERSPACE,
            Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            [membership.pk],
        ),
    }


class AdminMembershipRosterView(APIView):
    permission_classes = [IsActiveStaff]
    pagination_class = MembershipPagination

    @extend_schema(tags=["Admin memberships"], responses={200: AdminMembershipSerializer(many=True), **ERRORS})
    def get(self, request):
        makerspace = _makerspace(request.user, request.query_params.get("makerspace_id"))
        active = MakerspaceWaiver.objects.filter(makerspace=makerspace, is_active=True).first()
        queryset = MakerspaceMembership.objects.filter(makerspace=makerspace).select_related("user", "assigned_role").order_by("user__username")
        pager = self.pagination_class()
        page = pager.paginate_queryset(queryset, request)
        context = {
            "active_waiver_version": active.version if active else None,
            **scoped_payment_context(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
                [membership.pk for membership in page],
            ),
        }
        return pager.get_paginated_response(AdminMembershipSerializer(
            page, many=True, context=context
        ).data)


class AdminMembershipRequestListView(APIView):
    permission_classes = [IsActiveStaff]
    pagination_class = MembershipPagination

    @extend_schema(tags=["Admin memberships"], responses={200: MembershipRequestSerializer(many=True), **ERRORS})
    def get(self, request):
        makerspace = _makerspace(request.user, request.query_params.get("makerspace_id"))
        # Gated alongside approve/revoke: staff must not be shown a queue of community
        # join requests they have no enabled surface to action.
        require_module(makerspace, "membership")
        queryset = MembershipRequest.objects.filter(makerspace=makerspace).select_related("user", "assigned_role")
        if request.query_params.get("state"):
            queryset = queryset.filter(state=request.query_params["state"])
        pager = self.pagination_class()
        page = pager.paginate_queryset(queryset.order_by("-created_at"), request)
        return pager.get_paginated_response(MembershipRequestSerializer(page, many=True).data)


class AdminInvitationView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], request=InvitationSerializer, responses={201: MembershipRequestSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        makerspace = _makerspace(request.user, makerspace_id)
        serializer = InvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = membership_services.invite_membership(request.user, makerspace, serializer.validated_data["invite_email"], _role(makerspace, serializer.validated_data["role_id"]))
        return Response(MembershipRequestSerializer(item).data, status=status.HTTP_201_CREATED)


class AdminRequestApproveView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], request=RoleIdSerializer, responses={200: AdminMembershipSerializer, **ERRORS})
    def post(self, request, pk):
        item = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE, MembershipRequest.objects.select_related("makerspace")), pk=pk)
        makerspace = _makerspace(request.user, item.makerspace_id)
        require_module(makerspace, "membership")
        serializer = RoleIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = membership_services.approve_request(request.user, item, _role(makerspace, serializer.validated_data["role_id"]))
        membership = MakerspaceMembership.objects.select_related(
            "user", "assigned_role"
        ).get(pk=membership.pk)
        return Response(
            AdminMembershipSerializer(
                membership,
                context=_membership_context(request.user, membership),
            ).data
        )


class AdminRequestRevokeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], request=RevokeSerializer, responses={200: MembershipRequestSerializer, **ERRORS})
    def post(self, request, pk):
        item = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE, MembershipRequest.objects.select_related("makerspace")), pk=pk)
        require_module(_makerspace(request.user, item.makerspace_id), "membership")
        serializer = RevokeSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        item = membership_services.revoke_request(request.user, item, serializer.validated_data.get("reason", ""))
        return Response(MembershipRequestSerializer(item).data)


class AdminMembershipRevokeM2View(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], request=RevokeSerializer, responses={200: AdminMembershipSerializer, **ERRORS})
    def post(self, request, pk):
        membership = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE, MakerspaceMembership.objects.select_related("makerspace")), pk=pk)
        _makerspace(request.user, membership.makerspace_id)
        serializer = RevokeSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        membership = membership_services.revoke_membership(request.user, membership, serializer.validated_data.get("reason", ""))
        membership = MakerspaceMembership.objects.select_related(
            "user", "assigned_role"
        ).get(pk=membership.pk)
        return Response(
            AdminMembershipSerializer(
                membership,
                context=_membership_context(request.user, membership),
            ).data
        )


class AdminMembershipRoleM2View(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], request=RoleIdSerializer, responses={200: AdminMembershipSerializer, **ERRORS})
    def patch(self, request, pk):
        membership = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE, MakerspaceMembership.objects.select_related("makerspace")), pk=pk)
        makerspace = _makerspace(request.user, membership.makerspace_id)
        serializer = RoleIdSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        membership = membership_services.change_role(request.user, membership, _role(makerspace, serializer.validated_data["role_id"]))
        membership = MakerspaceMembership.objects.select_related(
            "user", "assigned_role"
        ).get(pk=membership.pk)
        return Response(
            AdminMembershipSerializer(
                membership,
                context=_membership_context(request.user, membership),
            ).data
        )


class AdminWaiverView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], request=WaiverPublishSerializer, responses={200: WaiverPublishSerializer, **ERRORS})
    def put(self, request, makerspace_id):
        makerspace = _makerspace(request.user, makerspace_id)
        serializer = WaiverPublishSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("clear"):
            waiver_services.deactivate_waiver(request.user, makerspace)
            return Response({"has_waiver": False})
        waiver = waiver_services.publish_waiver(request.user, makerspace, serializer.validated_data["body"], serializer.validated_data["version"])
        return Response({"has_waiver": True, "version": waiver.version})
