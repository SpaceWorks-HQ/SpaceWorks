import hashlib

from django.http import HttpResponse
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.events.member_history import registrations_for_space
from apps.events.models import Event
from apps.events.serializers_calendar import (
    MemberCalendarFeedIssuedSerializer,
    MemberCalendarFeedIssueSerializer,
    MemberCalendarFeedStateSerializer,
)
from apps.events.services_calendar import (
    render_member_calendar,
    render_public_event_calendar,
)
from apps.events.services_calendar_feeds import (
    feed_state,
    issue_or_rotate_feed,
    resolve_feed,
    revoke_feed,
)
from apps.events.throttles import (
    EventCalendarFeedIpThrottle,
    EventCalendarFeedTokenThrottle,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module, require_module_for_servable
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.member_activity_service import active_membership
from apps.makerspaces.platform import module_enabled


CALENDAR_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.BINARY,
    description="RFC 5545 calendar (`text/calendar; charset=utf-8`).",
)
CALENDAR_SUCCESS = {(200, "text/calendar"): CALENDAR_RESPONSE}
CALENDAR_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Events module unavailable."),
    404: OpenApiResponse(ErrorSerializer, description="Calendar not found."),
    429: OpenApiResponse(ErrorSerializer, description="Rate limit exceeded."),
}


def _calendar_response(payload, filename, request, *, private=False):
    etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(payload, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["ETag"] = etag
    response["Cache-Control"] = (
        "private, max-age=300, must-revalidate" if private else "public, max-age=300"
    )
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex"
    return response


def _member_membership(request, makerspace_id):
    membership = active_membership(request.user, makerspace_id)
    if membership is None:
        raise PermissionDenied("Active membership is required.")
    require_module(membership.makerspace, "events")
    return membership


class PublicEventCalendarView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(
        tags=["Public events"], auth=[], request=None,
        responses={**CALENDAR_SUCCESS, **CALENDAR_ERRORS},
    )
    def get(self, request, makerspace_slug, public_token):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module_for_servable(makerspace, "events")
        event = get_object_or_404(
            Event.objects.select_related("series").filter(
                makerspace=makerspace,
                public_token=public_token,
                is_public=True,
                status__in=(
                    Event.Status.PUBLISHED, Event.Status.COMPLETED, Event.Status.CANCELLED,
                ),
            )
        )
        return _calendar_response(
            render_public_event_calendar(event), f"event-{event.public_token}.ics", request
        )


class MemberEventCalendarView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member events"], request=None,
        responses={
            **CALENDAR_SUCCESS,
            401: OpenApiResponse(ErrorSerializer, description="Authentication required."),
            403: OpenApiResponse(ErrorSerializer, description="Active membership required."),
            404: OpenApiResponse(ErrorSerializer, description="Makerspace not found."),
            400: OpenApiResponse(ErrorSerializer, description="Events module unavailable."),
        },
    )
    def get(self, request, makerspace_id):
        membership = _member_membership(request, makerspace_id)
        rows = registrations_for_space(membership.makerspace, request.user)
        payload = render_member_calendar(membership.makerspace, rows)
        return _calendar_response(payload, "my-events.ics", request, private=True)


class MemberEventCalendarFeedView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member events"], request=None,
        responses={200: MemberCalendarFeedStateSerializer, 401: ErrorSerializer,
                   403: ErrorSerializer, 404: ErrorSerializer, 400: ErrorSerializer},
    )
    def get(self, request, makerspace_id):
        membership = _member_membership(request, makerspace_id)
        return Response(MemberCalendarFeedStateSerializer(feed_state(membership)).data)

    @extend_schema(
        tags=["Member events"], request=MemberCalendarFeedIssueSerializer,
        responses={200: MemberCalendarFeedIssuedSerializer, 400: ErrorSerializer,
                   401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer,
                   409: OpenApiResponse(ErrorSerializer, description="Concurrent rotation conflict.")},
    )
    def post(self, request, makerspace_id):
        membership = _member_membership(request, makerspace_id)
        serializer = MemberCalendarFeedIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feed, raw_token = issue_or_rotate_feed(membership, actor=request.user)
        path = reverse("public-event-calendar-feed", kwargs={
            "makerspace_slug": membership.makerspace.slug, "raw_token": raw_token,
        })
        result = {
            "feed_url": request.build_absolute_uri(path),
            "token_hint": feed.token_hint,
            "created_at": feed.created_at,
        }
        return Response(MemberCalendarFeedIssuedSerializer(result).data)

    @extend_schema(
        tags=["Member events"], request=None,
        responses={204: None, 401: ErrorSerializer, 403: ErrorSerializer,
                   404: ErrorSerializer, 400: ErrorSerializer},
    )
    def delete(self, request, makerspace_id):
        membership = _member_membership(request, makerspace_id)
        revoke_feed(membership, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicMemberEventCalendarFeedView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [EventCalendarFeedTokenThrottle, EventCalendarFeedIpThrottle]

    @extend_schema(
        tags=["Public events"], auth=[], request=None,
        responses={**CALENDAR_SUCCESS, 404: CALENDAR_ERRORS[404], 429: CALENDAR_ERRORS[429]},
    )
    def get(self, request, makerspace_slug, raw_token):
        feed = resolve_feed(raw_token)
        if feed is None:
            raise NotFound()
        membership = feed.membership
        if (
            membership.status != "active"
            or not membership.user.is_active
            or membership.user.access_status != "active"
            or membership.makerspace.slug != makerspace_slug
        ):
            raise NotFound()
        try:
            makerspace = get_public_makerspace(makerspace_slug)
        except Http404 as exc:
            raise NotFound() from exc
        if makerspace.pk != membership.makerspace_id or not module_enabled(makerspace, "events"):
            raise NotFound()
        rows = registrations_for_space(makerspace, membership.user)
        payload = render_member_calendar(makerspace, rows)
        return _calendar_response(payload, "my-events.ics", request, private=True)
