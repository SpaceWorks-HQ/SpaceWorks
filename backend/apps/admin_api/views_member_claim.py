from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.services_claim import (
    active_claim_codes,
    issue_claim_code,
    revoke_claim_code,
)
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_member_claim import (
    MemberClaimCodeIssueRequestSerializer,
    MemberClaimCodeIssueResponseSerializer,
    MemberClaimCodeSerializer,
)
from apps.admin_api.views_roles import ERRORS
from apps.boxes.qr_render import render_qr_label_svg
from apps.hardware_requests.exceptions import ErrorSerializer

CLAIM_ERRORS = {
    **ERRORS,
    429: OpenApiResponse(ErrorSerializer, description="Issue rate limit exceeded."),
}


class MemberClaimCodeListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    def get_throttles(self):
        # Listing does not spend the issuance budget. Redemption gets its own scope in
        # D5, so retries can never lock staff out of issuing a replacement credential.
        if self.request.method == "POST":
            self.throttle_scope = "member_claim_issue"
            return [ScopedRateThrottle()]
        return []

    @extend_schema(
        tags=["Admin memberships"],
        summary="List active physically handed member claim codes",
        responses={200: MemberClaimCodeSerializer(many=True), **ERRORS},
    )
    def get(self, request, makerspace_id):
        claims = active_claim_codes(actor=request.user, makerspace_id=makerspace_id)
        return Response(MemberClaimCodeSerializer(claims, many=True).data)

    @extend_schema(
        tags=["Admin memberships"],
        summary="Issue a claim code to an eligible walk-in member",
        request=MemberClaimCodeIssueRequestSerializer,
        responses={201: MemberClaimCodeIssueResponseSerializer, **CLAIM_ERRORS},
    )
    def post(self, request, makerspace_id):
        serializer = MemberClaimCodeIssueRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issued = issue_claim_code(
            actor=request.user,
            makerspace_id=makerspace_id,
            membership_id=serializer.validated_data["membership_id"],
        )
        payload = {
            **MemberClaimCodeSerializer(issued.claim).data,
            "code": issued.code,
            "qr_svg": render_qr_label_svg(issued.code),
        }
        return Response(payload, status=status.HTTP_201_CREATED)


class MemberClaimCodeRevokeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin memberships"],
        summary="Revoke a member claim code and its bound session",
        request=None,
        responses={200: MemberClaimCodeSerializer, **ERRORS},
    )
    def post(self, request, makerspace_id, claim_id):
        claim = revoke_claim_code(
            actor=request.user,
            makerspace_id=makerspace_id,
            claim_id=claim_id,
        )
        return Response(MemberClaimCodeSerializer(claim).data)
