from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.schemas_self_service import ACCOUNT_ERRORS as ERRORS
from apps.makerspaces.membership_self_service import cancel_renewal, leave_makerspace
from apps.makerspaces.self_service_access import own_membership


class MembershipAccountSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["active", "revoked"])
    renewal_cancelled_at = serializers.DateTimeField(allow_null=True)


class MembershipReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, allow_blank=False, trim_whitespace=True)




class MemberAccountMembershipView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Member account"], request=None,
                   responses={200: MembershipAccountSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        return Response(MembershipAccountSerializer(own_membership(request.user, makerspace_id)).data)


class MemberCancelRenewalView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Member account"], request=MembershipReasonSerializer,
                   responses={200: MembershipAccountSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        own_membership(request.user, makerspace_id)
        data = MembershipReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = cancel_renewal(request.user, makerspace_id, data.validated_data["reason"])
        return Response(MembershipAccountSerializer(row).data)


class MemberLeaveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Member account"], request=MembershipReasonSerializer,
                   responses={200: MembershipAccountSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        own_membership(request.user, makerspace_id)
        data = MembershipReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = leave_makerspace(request.user, makerspace_id, data.validated_data["reason"])
        return Response(MembershipAccountSerializer(row).data)
