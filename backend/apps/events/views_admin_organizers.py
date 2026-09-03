from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.events import services_organizers
from apps.events.serializers_organizers import (
    EventOrganizerListSerializer,
    EventOrganizerReplaceSerializer,
)
from apps.events.views_admin import _manageable_event
from apps.hardware_requests.exceptions import ErrorSerializer


class EventOrganizerView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"],
        summary="Replace an event's organization organizers",
        request=EventOrganizerReplaceSerializer,
        responses={
            200: EventOrganizerListSerializer,
            400: OpenApiResponse(description="Invalid or unavailable organization."),
            401: ErrorSerializer,
            403: ErrorSerializer,
            404: ErrorSerializer,
            409: OpenApiResponse(description="Concurrent event state conflict."),
        },
    )
    def put(self, request, pk):
        event = _manageable_event(request.user, pk)
        serializer = EventOrganizerReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = services_organizers.replace_organizers(
            event,
            actor=request.user,
            organization_ids=serializer.validated_data["organization_ids"],
        )
        return Response(EventOrganizerListSerializer(event).data)
