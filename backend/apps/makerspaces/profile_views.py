"""Member-facing profile and directory endpoints.

Every one requires an active membership of the makerspace in the path AND the
`membership` module. The directory is member-visible, never public: a space's roster is
not something a passer-by gets to enumerate, even reduced to display names.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hardware_requests.exceptions import ErrorSerializer
from apps.accounts.claim_sessions import claim_context
from apps.makerspaces import profile_services
from apps.makerspaces.guards import require_module
from apps.makerspaces.member_activity_service import active_membership
from apps.makerspaces.profile_serializers import (
    DirectorySerializer,
    ProfileReadSerializer,
    ProfileWriteSerializer,
)
from apps.presence.guard import MemberPresenceRequired

ERRORS = {
    401: OpenApiResponse(description="Authentication required."),
    403: OpenApiResponse(ErrorSerializer, description="An active membership is required."),
    404: OpenApiResponse(ErrorSerializer, description="Not found."),
}


class MemberProfileBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def membership(self, request, makerspace_id):
        membership = active_membership(request.user, makerspace_id)
        if membership is None:
            # The same 403 every other member-area endpoint raises. Deliberately not a
            # 404: whether a makerspace exists is already public.
            raise MemberPresenceRequired()
        require_module(membership.makerspace, "membership")
        return membership


class MemberProfileView(MemberProfileBaseView):
    @extend_schema(
        tags=["Member profile"], summary="Retrieve the caller's own profile",
        request=None, responses={200: ProfileReadSerializer, **ERRORS},
    )
    def get(self, request, makerspace_id):
        membership = self.membership(request, makerspace_id)
        return Response(
            ProfileReadSerializer(profile_services.read_profile(membership)).data
        )

    @extend_schema(
        tags=["Member profile"], summary="Update the caller's own profile",
        request=ProfileWriteSerializer,
        responses={200: ProfileReadSerializer, **ERRORS},
    )
    def put(self, request, makerspace_id):
        membership = self.membership(request, makerspace_id)
        serializer = ProfileWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile_services.save_profile(membership, serializer.validated_data)
        return Response(
            ProfileReadSerializer(profile_services.read_profile(membership)).data
        )


class MemberDirectoryView(MemberProfileBaseView):
    @extend_schema(
        tags=["Member profile"], summary="List members who published a profile",
        request=None, responses={200: DirectorySerializer, **ERRORS},
    )
    def get(self, request, makerspace_id):
        membership = self.membership(request, makerspace_id)
        return Response(
            DirectorySerializer(profile_services.directory(membership.makerspace)).data
        )


class MemberDirectoryDetailView(MemberProfileBaseView):
    @extend_schema(
        tags=["Member profile"], summary="Retrieve another member's published profile",
        request=None, responses={200: ProfileReadSerializer, **ERRORS},
    )
    def get(self, request, makerspace_id, membership_id):
        membership = self.membership(request, makerspace_id)
        payload = profile_services.visible_profile(
            membership.makerspace,
            membership_id,
            local_activity_only=claim_context(request.user) is not None,
        )
        if payload is None:
            # One 404 for "no such member", "not a member here" and "has not published",
            # because distinguishing them would answer questions about people who chose
            # not to be listed.
            from rest_framework.exceptions import NotFound

            raise NotFound()
        return Response(ProfileReadSerializer(payload).data)
