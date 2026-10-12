from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import active_user
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.membership_gating import is_staff_invitation
from apps.makerspaces.membership_services import claim_invitation, normalized_email
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.serializers_memberships import (
    InvitationClaimOutcomeSerializer,
    InvitationListSerializer,
)
from apps.makerspaces.servability import servable_queryset
from apps.makerspaces.serializers_admission import AdmissionAnswersSerializer


ERRORS = {400: ErrorSerializer, 401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer,
          423: ErrorSerializer, 503: ErrorSerializer}


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
        "is_staff": is_staff_invitation(invitation),
    }


class InvitationDiscoveryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Memberships"], responses={200: InvitationListSerializer, **ERRORS})
    def get(self, request):
        if not active_user(request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        # A community invitation or referral of a space that has since switched the
        # module off is not claimable (the claim answers 400), so it is not offered.
        invitations = [
            item for item in _claimable_invitations(request.user)
            if is_staff_invitation(item) or module_enabled(item.makerspace, "membership")
        ]
        return Response({"invitations": [_invitation_payload(item) for item in invitations]})


class InvitationClaimView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=AdmissionAnswersSerializer, tags=["Memberships"], responses={200: InvitationClaimOutcomeSerializer, **ERRORS})
    def post(self, request, pk):
        if not active_user(request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        invitation = get_object_or_404(_claimable_invitations(request.user), pk=pk)
        serializer = AdmissionAnswersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        claimed = claim_invitation(request.user, invitation.pk, serializer.validated_data.get("application_answers"))
        if isinstance(claimed, MakerspaceMembership):
            outcome = "active"
        else:
            outcome = claimed.state if claimed.state in ("awaiting_vouches", "awaiting_payment") else "pending_approval"
        return Response({"id": invitation.pk, "outcome": outcome})
