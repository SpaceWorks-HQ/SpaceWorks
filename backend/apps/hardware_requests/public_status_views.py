"""Public-token status reads remain available for existing loans."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.hardware_requests.serializers import PublicRequestStatusSerializer
from apps.hardware_requests.view_helpers import ERROR_401, ERROR_403, ERROR_404, ERROR_429
from apps.makerspaces.servability import servable_queryset
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS, PUBLIC_REQUEST_STATUS_EXAMPLE


class RequestStatusView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "request_status"
    serializer_class = PublicRequestStatusSerializer
    lookup_field = "public_token"

    def get_queryset(self):
        from apps.hardware_requests.view_helpers import request_queryset

        return servable_queryset(request_queryset(), relation="makerspace")

    @extend_schema(
        tags=["Public requests"],
        summary="Get request status by public token",
        auth=[],
        parameters=PUBLIC_API_AUTH_PARAMETERS,
        responses={200: PublicRequestStatusSerializer, 401: ERROR_401,
                   403: ERROR_403, 404: ERROR_404, 429: ERROR_429},
        examples=[PUBLIC_REQUEST_STATUS_EXAMPLE],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

