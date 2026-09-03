from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import user_payload
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.organizations import services_invitations
from apps.organizations.serializers_admin import (
    OrganizationInvitationRedeemedSerializer,
    OrganizationInvitationRedeemSerializer,
    OrganizationMembershipSerializer,
)


class OrganizationInvitationRedeemView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        summary="Redeem a single-use organization invitation",
        request=OrganizationInvitationRedeemSerializer,
        responses={
            200: OrganizationInvitationRedeemedSerializer,
            400: OpenApiResponse(description="Malformed token."),
            401: ErrorSerializer,
            403: ErrorSerializer,
            404: OpenApiResponse(description="Invitation not found."),
            409: ErrorSerializer,
        },
    )
    def post(self, request):
        serializer = OrganizationInvitationRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services_invitations.redeem_invitation(
            serializer.validated_data["token"], actor=request.user
        )
        return Response(
            {
                "membership": OrganizationMembershipSerializer(membership).data,
                "user": user_payload(request.user, request=request),
            },
            status=status.HTTP_200_OK,
        )
