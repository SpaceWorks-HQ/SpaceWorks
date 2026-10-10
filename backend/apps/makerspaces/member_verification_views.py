"""Delegated verification through member sessions, with the shared locked service."""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import active_user
from apps.admin_api.views_member_capabilities import _membership_for_verifier
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces import membership_services
from apps.makerspaces.guards import require_module


class MemberVerificationRequestSerializer(serializers.Serializer):
    membership_id = serializers.IntegerField(min_value=1)
    verified = serializers.BooleanField()


class MemberVerificationResponseSerializer(serializers.Serializer):
    membership_id = serializers.IntegerField()
    display_name = serializers.CharField()
    verified_at = serializers.DateTimeField(allow_null=True)


class MemberVerificationView(APIView):
    # A member route, like the referral route: any authenticated active account. The
    # scoped lookup and the locked service decide whether it holds can_verify or MANAGE.
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Memberships"], request=MemberVerificationRequestSerializer,
        responses={200: MemberVerificationResponseSerializer, **{
            code: ErrorSerializer for code in (400, 401, 403, 404)
        }},
    )
    def post(self, request, makerspace_id):
        if not active_user(request.user):
            raise PermissionDenied()
        serializer = MemberVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        membership = _membership_for_verifier(request.user, data["membership_id"])
        if membership.makerspace_id != makerspace_id:
            raise NotFound()
        require_module(membership.makerspace, "membership")
        operation = membership_services.verify_member if data["verified"] else membership_services.unverify_member
        membership = operation(request.user, membership)
        return Response({
            "membership_id": membership.pk,
            "display_name": membership.user.display_name or membership.user.username,
            "verified_at": membership.verified_at,
        })
