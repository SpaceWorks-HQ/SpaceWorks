from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from apps.admin_api.list_options import LIST_PARAMETERS, ORDER_PAGE_PARAMETERS, choice_filter, identity_filter, order_list
from apps.admin_api.serializers_member_list import MembershipListResponseSerializer, MembershipRequestListResponseSerializer
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_member_memberships import (AdminMembershipSerializer, ApproveRequestSerializer,
    InvitationSerializer, MembershipRequestSerializer, RevokeSerializer, RoleIdSerializer)
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.admin_api.views_roles import ERRORS
from apps.makerspaces import membership_services, waiver_services
from apps.makerspaces.guards import require_module
from apps.makerspaces.membership_gating import require_module_for_request, staff_invitation_q
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole, MakerspaceWaiver, MembershipPlan, MembershipRequest
from apps.makerspaces.serializers_memberships import MemberWaiverResponseSerializer, WaiverPublishSerializer
from apps.makerspaces.servability import servable_queryset
from apps.payments.models import Payment


class MembershipPagination(PageNumberPagination):
    page_size = 24


def _makerspace(actor, makerspace_id, action=rbac.Action.MANAGE_MEMBERS):
    queryset = rbac.scope_by_action(
        actor, action, servable_queryset(), field="id"
    )
    makerspace = get_object_or_404(queryset, pk=makerspace_id)
    if not rbac.can(actor, action, makerspace.id):
        raise PermissionDenied()
    return makerspace


def _role(makerspace, role_id):
    return get_object_or_404(MakerspaceRole.objects.filter(makerspace=makerspace), pk=role_id)


def _membership_context(actor, membership, **extra):
    return {
        **extra,
        **scoped_payment_context(
            actor,
            rbac.Action.VIEW_FINANCE,
            Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            [membership.pk],
        ),
    }


class AdminMembershipRosterView(APIView):
    permission_classes = [IsActiveStaff]
    pagination_class = MembershipPagination

    @extend_schema(description="Requires manage_members in this makerspace; staff role administration and waiver publishing require manage_makerspace.", tags=["Admin memberships"], parameters=[*LIST_PARAMETERS, OpenApiParameter("makerspace_id", int, required=True), OpenApiParameter("status", str), OpenApiParameter("id", int, description="Select one membership within the authorized roster.")], responses={200: MembershipListResponseSerializer, **ERRORS})
    def get(self, request):
        makerspace = _makerspace(request.user, request.query_params.get("makerspace_id"))
        active = rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS, MakerspaceWaiver.objects.filter(makerspace=makerspace, is_active=True)).first()
        queryset = MakerspaceMembership.objects.filter(makerspace=makerspace).select_related("user", "assigned_role").order_by("user__username")
        queryset = rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS, queryset)
        selected_id = identity_filter(request.query_params)
        if selected_id is not None:
            queryset = queryset.filter(pk=selected_id)
        if request.query_params.get("q"):
            queryset = queryset.filter(user__username__icontains=request.query_params["q"])
        selected_status = choice_filter(request.query_params, "status", dict(MakerspaceMembership._meta.get_field("status").choices))
        if selected_status:
            queryset = queryset.filter(status=selected_status)
        queryset = order_list(queryset, request.query_params, {"user__username", "status", "created_at"}, "user__username")
        pager = self.pagination_class()
        page = pager.paginate_queryset(queryset, request)
        context = {
            # Resolved once for the whole roster. The waiver predicates take it as an
            # explicit argument precisely so a per-row lookup cannot become an N+1.
            "active_waiver": active,
            **scoped_payment_context(
                request.user,
                rbac.Action.VIEW_FINANCE,
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

    @extend_schema(description="Requires manage_members in this makerspace; staff role administration and waiver publishing require manage_makerspace.", tags=["Admin memberships"], parameters=[*ORDER_PAGE_PARAMETERS, OpenApiParameter("makerspace_id", int, required=True), OpenApiParameter("state", str)], responses={200: MembershipRequestListResponseSerializer, **ERRORS})
    def get(self, request):
        makerspace = _makerspace(request.user, request.query_params.get("makerspace_id"))
        queryset = MembershipRequest.objects.filter(makerspace=makerspace).select_related("user", "assigned_role")
        queryset = rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS, queryset)
        if not module_enabled(makerspace, "membership"):
            # Staff must not be shown community join requests they have no enabled surface
            # to action -- but a STAFF invitation is core RBAC business and must stay
            # visible, or one issued with the module off could never be found again.
            queryset = queryset.filter(staff_invitation_q())
        selected_state = choice_filter(request.query_params, "state", MembershipRequest.State.values)
        if selected_state:
            queryset = queryset.filter(state=selected_state)
        pager = self.pagination_class()
        page = pager.paginate_queryset(order_list(queryset, request.query_params, {"created_at", "state"}, "-created_at"), request)
        return pager.get_paginated_response(MembershipRequestSerializer(page, many=True).data)


class AdminInvitationView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(description="Requires manage_members in this makerspace; staff role administration and waiver publishing require manage_makerspace.", tags=["Admin memberships"], request=InvitationSerializer, responses={201: MembershipRequestSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        makerspace = _makerspace(request.user, makerspace_id)
        serializer = InvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = membership_services.invite_membership(request.user, makerspace, serializer.validated_data["invite_email"], _role(makerspace, serializer.validated_data["role_id"]))
        return Response(MembershipRequestSerializer(item).data, status=status.HTTP_201_CREATED)


class AdminRequestApproveView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(description="Requires manage_members in this makerspace; staff role administration and waiver publishing require manage_makerspace.", tags=["Admin memberships"], request=ApproveRequestSerializer, responses={200: AdminMembershipSerializer, **ERRORS})
    def post(self, request, pk):
        item = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS, MembershipRequest.objects.select_related("makerspace")), pk=pk)
        makerspace = _makerspace(request.user, item.makerspace_id)
        serializer = ApproveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = _role(makerspace, serializer.validated_data["role_id"])
        require_module_for_request(makerspace, item, outcome_role=role)
        plan = None
        if serializer.validated_data.get("plan_id") is not None:
            # Plans are the module's own surface, whatever the request is.
            require_module(makerspace, "membership")
            plan = get_object_or_404(MembershipPlan.objects.filter(makerspace=makerspace), pk=serializer.validated_data["plan_id"])
        membership = membership_services.approve_request(request.user, item, role, plan=plan)
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

    @extend_schema(description="Requires manage_members in this makerspace; staff role administration and waiver publishing require manage_makerspace.", tags=["Admin memberships"], request=RevokeSerializer, responses={200: MembershipRequestSerializer, **ERRORS})
    def post(self, request, pk):
        item = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS, MembershipRequest.objects.select_related("makerspace")), pk=pk)
        require_module_for_request(_makerspace(request.user, item.makerspace_id), item)
        serializer = RevokeSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        item = membership_services.revoke_request(request.user, item, serializer.validated_data.get("reason", ""))
        return Response(MembershipRequestSerializer(item).data)


class AdminMembershipRevokeM2View(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(description="Requires manage_members in this makerspace; staff role administration and waiver publishing require manage_makerspace.", tags=["Admin memberships"], request=RevokeSerializer, responses={200: AdminMembershipSerializer, **ERRORS})
    def post(self, request, pk):
        membership = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS, MakerspaceMembership.objects.select_related("makerspace")), pk=pk)
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

    @extend_schema(description="Requires manage_members in this makerspace; staff role administration and waiver publishing require manage_makerspace.", tags=["Admin memberships"], request=RoleIdSerializer, responses={200: AdminMembershipSerializer, **ERRORS})
    def patch(self, request, pk):
        membership = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS, MakerspaceMembership.objects.select_related("makerspace")), pk=pk)
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

    @extend_schema(description="Requires manage_members in this makerspace; staff role administration and waiver publishing require manage_makerspace.", tags=["Admin memberships"], responses={200: MemberWaiverResponseSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        makerspace = _makerspace(request.user, makerspace_id)
        waiver = MakerspaceWaiver.objects.filter(makerspace=makerspace, is_active=True).first()
        return Response({"has_waiver": False} if waiver is None else {
            "has_waiver": True, "version": waiver.version, "body": waiver.body,
        })

    @extend_schema(description="Requires manage_makerspace in this makerspace to publish or clear waiver text.", tags=["Admin memberships"], request=WaiverPublishSerializer, responses={200: MemberWaiverResponseSerializer, **ERRORS})
    def put(self, request, makerspace_id):
        makerspace = _makerspace(request.user, makerspace_id, rbac.Action.MANAGE_MAKERSPACE)
        serializer = WaiverPublishSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("clear"):
            waiver_services.deactivate_waiver(request.user, makerspace)
            return Response({"has_waiver": False})
        waiver = waiver_services.publish_waiver(request.user, makerspace, serializer.validated_data["body"], serializer.validated_data["version"])
        return Response({"has_waiver": True, "version": waiver.version})
