from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.member_activity_serializers import MemberActivitySerializer
from apps.makerspaces.member_activity_service import active_membership, member_activity
from apps.presence.guard import MemberPresenceRequired


ERRORS = {
    401: OpenApiResponse(description="Authentication required."),
    403: OpenApiResponse(ErrorSerializer, description="An active membership is required."),
    404: OpenApiResponse(ErrorSerializer, description="Makerspace not found."),
}


class MemberActivityView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member activity"], summary="Retrieve the caller's makerspace activity",
        request=None, responses={200: MemberActivitySerializer, **ERRORS},
    )
    def get(self, request, makerspace_id):
        membership = active_membership(request.user, makerspace_id)
        if membership is None:
            raise MemberPresenceRequired()
        require_module(membership.makerspace, "membership")
        return Response(MemberActivitySerializer(member_activity(membership)).data)
