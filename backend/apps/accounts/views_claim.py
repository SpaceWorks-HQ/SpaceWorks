from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.auth_cookies import set_refresh_cookies
from apps.accounts.claim_sessions import attach_claim_context
from apps.accounts.claim_tokens import mint_claim_tokens
from apps.accounts.serializers import user_payload
from apps.accounts.serializers_claim import (
    ClaimRedemptionResponseSerializer,
    ClaimRedemptionSerializer,
)
from apps.accounts.services_claim import consume_claim_code
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.lookup import get_public_makerspace
from apps.tenant_migration.gate_runtime import tenant_write


class ClaimRedemptionView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "member_claim_redeem"

    @extend_schema(
        tags=["Auth"],
        summary="Redeem a staff-issued member claim code",
        auth=[],
        request=ClaimRedemptionSerializer,
        responses={
            200: ClaimRedemptionResponseSerializer,
            400: OpenApiResponse(ErrorSerializer, description="Invalid or expired claim code."),
            404: OpenApiResponse(description="Makerspace not found."),
            429: OpenApiResponse(description="Redemption rate limit exceeded."),
        },
    )
    def post(self, request):
        serializer = ClaimRedemptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        makerspace = get_public_makerspace(
            serializer.validated_data["makerspace_slug"]
        )
        with tenant_write(makerspace.pk):
            claim = consume_claim_code(
                serializer.validated_data["code"],
                redemption_ip=request.META.get("REMOTE_ADDR") or "0.0.0.0",
                makerspace_id=makerspace.pk,
            )
            pair = mint_claim_tokens(claim)
            user = attach_claim_context(claim.membership.user, claim)
            response = Response(
                {"access": pair.access, "user": user_payload(user, request=request)}
            )
            set_refresh_cookies(response, pair.refresh, request)
            return response
