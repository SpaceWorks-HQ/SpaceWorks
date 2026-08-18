from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.inventory.public_stats import build_public_stats
from apps.inventory.serializers import PublicStatsSerializer
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS


@extend_schema(
    tags=["Public inventory"],
    summary="Get public makerspace stats",
    description="Get public activity stats for a public makerspace.",
    parameters=[
        *PUBLIC_API_AUTH_PARAMETERS,
        OpenApiParameter(
            name="makerspace_slug",
            type=str,
            location=OpenApiParameter.PATH,
            description="Public makerspace code (for example TSEL) or slug.",
        ),
    ],
    responses=PublicStatsSerializer,
)
class PublicMakerspaceStatsView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_stats"

    def get(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        if (
            not makerspace.public_inventory_enabled
            or not makerspace.public_stats_enabled
            or not module_enabled(
                makerspace,
                "public_inventory",
            )
        ):
            raise Http404

        serializer = PublicStatsSerializer(build_public_stats(makerspace))
        return Response(serializer.data)
