"""Public "ask to be invited" endpoint on the makerspace site.

Anonymous, throttled per client, honeypotted exactly like `RequestSubmitView`: the hidden
`website` field being filled returns the SAME 202 acknowledgement a real submission gets
and stores nothing, so a bot cannot tell the two apart. The module gate answers 404 --
a makerspace without `membership` has no invitation queue to fill.
"""
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.public_views import _honeypot_filled
from apps.makerspaces.editions import require_public_surface
from apps.makerspaces.invitation_request_services import submit_invitation_request
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset

ACK = {"detail": "Thanks - the makerspace will be in touch."}


class InvitationRequestCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    message = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default=""
    )
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)


class InvitationRequestAckSerializer(serializers.Serializer):
    detail = serializers.CharField()


class PublicInvitationRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_invitation_request"

    @extend_schema(
        tags=["Memberships"],
        summary="Ask a makerspace to invite you",
        request=InvitationRequestCreateSerializer,
        responses={
            202: InvitationRequestAckSerializer,
            400: ErrorSerializer,
            404: OpenApiResponse(description="Unknown makerspace or membership disabled."),
            429: ErrorSerializer,
        },
    )
    def post(self, request, makerspace_slug):
        makerspace = get_object_or_404(servable_queryset(), slug=makerspace_slug)
        # The honeypot precedes the module check and the serializer, as on request submit:
        # a bot gets its fake success before it learns anything about this space.
        if _honeypot_filled(request.data):
            return Response(ACK, status=status.HTTP_202_ACCEPTED)
        require_public_surface("membership")
        if not module_enabled(makerspace, "membership"):
            raise Http404()
        serializer = InvitationRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        submit_invitation_request(
            makerspace,
            name=data["name"],
            email=data["email"],
            phone=data.get("phone", ""),
            message=data.get("message", ""),
        )
        return Response(ACK, status=status.HTTP_202_ACCEPTED)
