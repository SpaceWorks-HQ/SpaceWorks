"""Member cancellation uses durable registration ownership, never contact fields."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events import services
from apps.events.member_history import registrations_for_space
from apps.events.models import EventRegistration
from apps.events.serializers_admin import EmptyActionSerializer
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.member_activity_service import active_membership
from apps.presence.guard import MemberPresenceRequired


class MemberRegistrationCancelResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[EventRegistration.Status.CANCELLED], read_only=True,
    )


class MemberEventRegistrationCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member events"],
        summary="Cancel the caller's event registration",
        description=(
            "Releases pending charges and uses the event's existing waitlist promotion "
            "policy. Settled charges are retained; this action does not issue a refund."
        ),
        request=EmptyActionSerializer,
        responses={
            200: MemberRegistrationCancelResponseSerializer,
            400: OpenApiResponse(
                {"type": "object", "additionalProperties": {}},
                description="Invalid body or events module disabled (field-keyed errors).",
            ),
            401: OpenApiResponse(ErrorSerializer, description="Authentication is required."),
            403: OpenApiResponse(ErrorSerializer, description="An active membership is required."),
            404: OpenApiResponse(ErrorSerializer, description="Owned registration not found."),
            409: OpenApiResponse(ErrorSerializer, description="Registration cannot be cancelled."),
        },
    )
    def post(self, request, makerspace_id, pk):
        membership = active_membership(request.user, makerspace_id)
        if membership is None:
            raise MemberPresenceRequired()
        space = membership.makerspace
        require_module(space, "events")
        # Check the host gate before the history helper filters disabled hosts out,
        # so a module-off cancellation returns 400 rather than a misleading 404.
        registration = get_object_or_404(
            registrations_for_space(space, request.user, include_disabled_hosts=True)
            .select_related("event__makerspace"),
            pk=pk,
        )
        require_module(registration.event.makerspace, "events")
        serializer = EmptyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        registration = services.cancel_registration(registration, actor=request.user)
        return Response(MemberRegistrationCancelResponseSerializer(registration).data)
