import re

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.events.badge_rendering import render_badges_pdf
from apps.events.exceptions import EventInvalidTransition
from apps.events.models import EventRegistration
from apps.events.serializers_badges import BadgePdfRequestSerializer, BadgeTemplateSerializer
from apps.events.services_badges import prepare_badges, save_badge_template
from apps.events.views_admin_events import EVENT_ERROR_400, EVENT_ERROR_409, _manageable_event
from apps.hardware_requests.exceptions import ErrorSerializer


def _filename(title):
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-")[:80]
    return f"{value or 'event'}-badges.pdf"


class EventBadgeTemplateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"], request=None,
        responses={200: BadgeTemplateSerializer, 403: ErrorSerializer, 404: ErrorSerializer},
    )
    def get(self, request, pk):
        event = _manageable_event(request.user, pk)
        from apps.events.badge_templates import normalize_badge_template

        return Response(normalize_badge_template(event.badge_template, event))

    @extend_schema(
        tags=["Admin events"], request=BadgeTemplateSerializer,
        responses={200: BadgeTemplateSerializer, 400: EVENT_ERROR_400,
                   403: ErrorSerializer, 404: ErrorSerializer, 409: EVENT_ERROR_409},
    )
    def put(self, request, pk):
        event = _manageable_event(request.user, pk)
        serializer = BadgeTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        normalized = save_badge_template(event, serializer.validated_data, actor=request.user)
        return Response(normalized)


class EventBadgePdfView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin events"], request=BadgePdfRequestSerializer,
        responses={
            (200, "application/pdf"): OpenApiResponse(
                OpenApiTypes.BINARY, description="Print-ready badge PDF."
            ),
            400: EVENT_ERROR_400, 403: ErrorSerializer, 404: ErrorSerializer, 409: EVENT_ERROR_409,
        },
    )
    def post(self, request, pk):
        event = _manageable_event(request.user, pk)
        serializer = BadgePdfRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            template, snapshots = prepare_badges(
                event, actor=request.user, **serializer.validated_data
            )
        except EventRegistration.DoesNotExist as exc:
            raise NotFound("A selected registration was not found for this event.") from exc
        payload = render_badges_pdf(template, snapshots, title=f"{event.title} attendee badges")
        response = HttpResponse(payload, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{_filename(event.title)}"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
