"""Staff queue for public invitation requests: list, invite, decline.

`MANAGE_MAKERSPACE` surfaces, module-gated by `membership`. "Invite" calls the ordinary
`membership_services.invite_membership`, so the invitation it produces is subject to the
same role non-escalation and community/staff discrimination as one typed in by hand.
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_member_memberships import RoleIdSerializer
from apps.admin_api.serializers_membership_plans import InvitationRequestSerializer
from apps.admin_api.views_member_memberships import _makerspace as manageable_makerspace
from apps.makerspaces.guards import require_module
from apps.makerspaces.invitation_request_services import decline_request, invite_from_request
from apps.makerspaces.models import InvitationRequest, MakerspaceRole

INVALID = OpenApiResponse(description="Invalid input or request already handled.")


def _row(actor, pk):
    row = get_object_or_404(
        rbac.scope_by_action(
            actor,
            rbac.Action.MANAGE_MAKERSPACE,
            InvitationRequest.objects.select_related("makerspace"),
        ),
        pk=pk,
    )
    require_module(manageable_makerspace(actor, row.makerspace_id), "membership")
    return row


class InvitationRequestListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        summary="List invitation requests (optionally filtered by ?status=)",
        responses={200: InvitationRequestSerializer(many=True)},
    )
    def get(self, request, makerspace_id):
        makerspace = require_module(
            manageable_makerspace(request.user, makerspace_id), "membership"
        )
        rows = InvitationRequest.objects.filter(makerspace=makerspace)
        wanted = request.query_params.get("status")
        if wanted in InvitationRequest.Status.values:
            rows = rows.filter(status=wanted)
        return Response(
            InvitationRequestSerializer(rows.order_by("-created_at", "-pk"), many=True).data
        )


class InvitationRequestInviteView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        summary="Turn an invitation request into a membership invitation",
        request=RoleIdSerializer,
        responses={200: InvitationRequestSerializer, 400: INVALID},
    )
    def post(self, request, pk):
        row = _row(request.user, pk)
        serializer = RoleIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = get_object_or_404(
            MakerspaceRole.objects.filter(makerspace_id=row.makerspace_id),
            pk=serializer.validated_data["role_id"],
        )
        return Response(InvitationRequestSerializer(invite_from_request(request.user, row, role)).data)


class InvitationRequestDeclineView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        summary="Decline an invitation request",
        request=None,
        responses={200: InvitationRequestSerializer, 400: INVALID},
    )
    def post(self, request, pk):
        row = _row(request.user, pk)
        return Response(InvitationRequestSerializer(decline_request(request.user, row)).data)
