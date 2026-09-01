"""Front-desk creation of a person record for someone who holds no account.

Gated on `ISSUE_DIRECT_LOAN` rather than `MANAGE_MAKERSPACE`: naming the stranger at the
counter is the same front-desk act as handing them a tool, and both Space Manager and
Inventory Manager already hold it, as does any custom handover role. Requiring the
makerspace-wide action instead would mean the person who cannot complete a handout
without it has to call a manager to create the borrower first.

Deliberately **not** gated by a module. See `makerspaces.walk_in_services` for why: this
is the identity path an accounts-off deployment runs on, while person records and staff
RBAC remain core regardless of self-service enrolment settings.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.views_roles import ERRORS
from apps.hardware_requests.direct_loan_serializers import DirectLoanMemberSerializer
from apps.hardware_requests.direct_loan_views import _makerspace_for_action, _require
from apps.makerspaces.walk_in_services import create_walk_in_member


class WalkInMemberCreateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=200)
    # Both optional: a walk-in may give only a name, and the record is worth having
    # anyway -- the Hard Rules need a named person on the handover, not a reachable one.
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")


class WalkInMemberCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        summary="Create a walk-in member record",
        request=WalkInMemberCreateSerializer,
        responses={201: DirectLoanMemberSerializer, **ERRORS},
    )
    def post(self, request, makerspace_id):
        makerspace = _makerspace_for_action(
            request.user, rbac.Action.ISSUE_DIRECT_LOAN, makerspace_id
        )
        _require(request.user, rbac.Action.ISSUE_DIRECT_LOAN, makerspace.id)
        serializer = WalkInMemberCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        membership = create_walk_in_member(
            request.user,
            makerspace,
            display_name=data["display_name"],
            email=data.get("email", ""),
            phone=data.get("phone", ""),
        )
        return Response(
            DirectLoanMemberSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )
