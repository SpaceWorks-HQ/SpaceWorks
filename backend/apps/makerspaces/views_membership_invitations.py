from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import active_user
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.membership_services import claim_invitation, normalized_email
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.makerspaces.serializers_memberships import (
    InvitationClaimOutcomeSerializer,
    InvitationListSerializer,
)
from apps.makerspaces.servability import servable_queryset


ERRORS = {400: ErrorSerializer, 401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer}


def _claimable_invitations(user):
    if not user.email_verified_at or not user.email:
        return MembershipRequest.objects.none()
    return servable_queryset(MembershipRequest.objects.filter(
        kind=MembershipRequest.Kind.INVITE,
        state=MembershipRequest.State.INVITED,
        invite_email=normalized_email(user.email),
    ), relation="makerspace").select_related("makerspace", "invited_by", "assigned_role")


def _invitation_payload(invitation):
    return {
        "id": invitation.id,
        "makerspace": {"slug": invitation.makerspace.slug, "name": invitation.makerspace.name},
        "inviter": invitation.invited_by.display_name if invitation.invited_by_id else None,
        "auto_activates": invitation.auto_activate_on_claim,
        "role": invitation.assigned_role.name if invitation.assigned_role_id else None,
    }


class InvitationDiscoveryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Memberships"], responses={200: InvitationListSerializer, **ERRORS})
    def get(self, request):
        if not active_user(request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        invitations = _claimable_invitations(request.user)
        return Response({"invitations": [_invitation_payload(item) for item in invitations]})


class InvitationClaimView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, tags=["Memberships"], responses={200: InvitationClaimOutcomeSerializer, **ERRORS})
    def post(self, request, pk):
        if not active_user(request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        invitation = get_object_or_404(_claimable_invitations(request.user), pk=pk)
        claimed = claim_invitation(request.user, invitation.pk)
        if isinstance(claimed, MakerspaceMembership):
            outcome = "active"
        else:
            outcome = "pending_approval"
        return Response({"id": invitation.pk, "outcome": outcome})
