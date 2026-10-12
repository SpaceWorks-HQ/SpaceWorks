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

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.views_roles import ERRORS as ROLE_ERRORS
from apps.hardware_requests.direct_loan_serializers import DirectLoanMemberSerializer
from apps.hardware_requests.direct_loan_views import _makerspace_for_action, _require
from apps.makerspaces.walk_in_services import create_walk_in_member
from apps.makerspaces.serializers_admission import AdmissionRequestSerializer, PublicAdmissionSerializer
from apps.makerspaces.views_admission import public_admission_payload
from apps.makerspaces.models import MembershipRequest
from apps.makerspaces.membership_admission_settings import settings_for
from apps.makerspaces.platform import module_enabled

ERRORS = {**ROLE_ERRORS, 423: ROLE_ERRORS[400], 503: ROLE_ERRORS[400]}


class WalkInMemberCreateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=200)
    # Both optional: a walk-in may give only a name, and the record is worth having
    # anyway -- the Hard Rules need a named person on the handover, not a reachable one.
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    application_answers = serializers.JSONField(required=False, allow_null=True)


class WalkInAdmissionOutcomeSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    display_name = serializers.CharField()
    username = serializers.CharField()
    admission_request = AdmissionRequestSerializer()


class WalkInMemberCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin memberships"], summary="Read walk-in admission questions", responses={200: PublicAdmissionSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        makerspace = _makerspace_for_action(request.user, rbac.Action.ISSUE_DIRECT_LOAN, makerspace_id)
        _require(request.user, rbac.Action.ISSUE_DIRECT_LOAN, makerspace.id)
        payload = public_admission_payload(makerspace)
        if not module_enabled(makerspace, "membership") or not settings_for(makerspace).configured:
            # The core legacy path immediately creates a borrower; dormant admission
            # settings must not make the client block that still-authorized action.
            payload.update(join_mode="open", application_schema=None, default_plan=None,
                           payment_timing="after_activation")
            if not module_enabled(makerspace, "membership"):
                payload["joining_fee"] = 0
        return Response(PublicAdmissionSerializer(payload).data)

    @extend_schema(
        tags=["Admin memberships"],
        summary="Create a walk-in member record",
        request=WalkInMemberCreateSerializer,
        responses={201: PolymorphicProxySerializer(component_name="WalkInAdmissionResult", serializers=[DirectLoanMemberSerializer, WalkInAdmissionOutcomeSerializer], resource_type_field_name=None), **ERRORS},
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
            application_answers=data.get("application_answers"),
        )
        if isinstance(membership, MembershipRequest):
            return Response({"user_id": membership.user_id, "display_name": membership.user.display_name,
                             "username": membership.user.username,
                             "admission_request": AdmissionRequestSerializer(membership).data}, status=status.HTTP_201_CREATED)
        return Response(
            DirectLoanMemberSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )
