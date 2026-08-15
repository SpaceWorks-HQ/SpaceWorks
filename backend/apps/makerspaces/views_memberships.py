from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.admin_api.permissions import active_user
from apps.accounts.models import User
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.membership_services import request_membership
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceWaiver, MembershipRequest
from apps.makerspaces.serializers_memberships import (
    MembershipOutcomeSerializer,
    MembershipRequestCreateSerializer,
    MemberWaiverResponseSerializer,
    MyMembershipsSerializer,
)
from apps.makerspaces.waiver_services import accept_waiver
from apps.makerspaces.waiver_state import acceptance_on_file, current_acceptance

ERRORS = {400: ErrorSerializer, 401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer, 409: ErrorSerializer, 429: ErrorSerializer}


def _membership(user, makerspace_id):
    return get_object_or_404(
        MakerspaceMembership.objects.select_related("makerspace", "assigned_role").filter(
            user=user, user__is_active=True, user__access_status=User.AccessStatus.ACTIVE,
            makerspace_id=makerspace_id, status="active", makerspace__archived_at__isnull=True
        )
    )


class PublicMembershipRequestView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "membership_request"

    @extend_schema(
        tags=["Memberships"],
        request=MembershipRequestCreateSerializer,
        responses={201: MembershipOutcomeSerializer, **ERRORS},
    )
    def post(self, request, makerspace_slug):
        if not active_user(request.user):
            raise PermissionDenied()
        makerspace = get_object_or_404(Makerspace.objects.filter(archived_at__isnull=True), slug=makerspace_slug)
        require_module(makerspace, "membership")
        serializer = MembershipRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        outcome = request_membership(request.user, makerspace)
        return Response(MembershipOutcomeSerializer(outcome).data, status=201)


class MyMembershipsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Memberships"], responses={200: MyMembershipsSerializer, **ERRORS})
    def get(self, request):
        if not active_user(request.user):
            raise PermissionDenied()
        memberships = MakerspaceMembership.objects.filter(user=request.user, makerspace__archived_at__isnull=True).select_related("makerspace", "assigned_role")
        requests = MembershipRequest.objects.filter(user=request.user, makerspace__archived_at__isnull=True).select_related("makerspace")
        rows = []
        for membership in memberships:
            active = MakerspaceWaiver.objects.filter(makerspace=membership.makerspace, is_active=True).first()
            rows.append({"makerspace": {"slug": membership.makerspace.slug, "name": membership.makerspace.name},
                         "membership_status": membership.status,
                         "role": membership.assigned_role.name if membership.assigned_role_id else membership.get_role_display(),
                         "actions": sorted(membership.assigned_role.granted_actions) if membership.assigned_role_id else [],
                         "can_refer": membership.can_refer,
                         "can_verify": membership.can_verify,
                         "verified_at": membership.verified_at,
                         "referrals_enabled": membership.makerspace.referrals_enabled,
                         "waiver_accepted": acceptance_on_file(membership),
                         "waiver_acceptance_required": bool(active and not current_acceptance(membership, active_waiver=active))})
        return Response({"memberships": rows, "requests": [
            {"makerspace": {"slug": item.makerspace.slug, "name": item.makerspace.name}, "state": item.state, "kind": item.kind}
            for item in requests
        ]})


class MemberWaiverView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Memberships"],
        responses={200: MemberWaiverResponseSerializer, **ERRORS},
    )
    def get(self, request, makerspace_id):
        if not active_user(request.user):
            raise PermissionDenied()
        membership = _membership(request.user, makerspace_id)
        waiver = MakerspaceWaiver.objects.filter(makerspace_id=makerspace_id, is_active=True).first()
        if waiver is None:
            return Response({"has_waiver": False})
        return Response({"has_waiver": True, "body": waiver.body, "version": waiver.version})


class MemberWaiverAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, tags=["Memberships"], responses={200: inline_serializer("WaiverAcceptResponse", {"accepted": serializers.BooleanField(), "version": serializers.CharField(allow_null=True)}), **ERRORS})
    def post(self, request, makerspace_id):
        if not active_user(request.user):
            raise PermissionDenied()
        membership = _membership(request.user, makerspace_id)
        membership, waiver = accept_waiver(membership)
        return Response({"accepted": waiver is not None, "version": waiver.version if waiver else None})
