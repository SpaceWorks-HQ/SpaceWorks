"""Staff API for server-derived, witnessed membership-waiver evidence."""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_member_memberships import (
    WitnessWaiverRequestSerializer,
    WitnessWaiverResponseSerializer,
)
from apps.admin_api.views_roles import ERRORS
from apps.makerspaces.waiver_services import witness_waiver_acceptance


class AdminWitnessWaiverAcceptanceView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        request=WitnessWaiverRequestSerializer,
        responses={200: WitnessWaiverResponseSerializer, **ERRORS},
    )
    def post(self, request, pk):
        serializer = WitnessWaiverRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership, waiver = witness_waiver_acceptance(request.user, pk)
        return Response(
            WitnessWaiverResponseSerializer(
                {
                    "membership_id": membership.id,
                    "waiver_id": waiver.id,
                    "waiver_version": waiver.version,
                    "witnessed_at": membership.witnessed_at,
                }
            ).data
        )
