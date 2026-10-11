from django.shortcuts import get_object_or_404
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.events.invites import create_invite, revoke_invite, require_feature
from apps.events.models import EventInvite
from apps.events.organizer_authority import organizer_event_q
from apps.events.views_admin_event_detail import _manageable_event
from apps.events.serializers_admin import EmptyActionSerializer
from apps.events.serializers_ticketing import InviteInputSerializer, InviteSerializer, InviteListSerializer
from apps.hardware_requests.exceptions import ErrorSerializer


ERRORS = {code: ErrorSerializer for code in (400, 401, 403, 404, 409, 423, 429, 503)}
ERRORS[400] = OpenApiResponse(
    {"type": "object", "additionalProperties": {}},
    description="Invalid field values, disabled events module or disabled feature.",
)
PAGE_PARAMETERS = [OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY)]


def paginated(request, queryset, serializer):
    paginator = PageNumberPagination()
    paginator.page_size = 24
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(serializer(page, many=True).data)


def manageable_event_code(actor, queryset, pk):
    venue_scoped = rbac.scope_by_visibility_or_action(
        actor, rbac.Action.MANAGE_EVENTS, queryset, field="event__makerspace_id",
    )
    row = get_object_or_404(queryset.filter(
        Q(pk__in=venue_scoped.values("pk")) | organizer_event_q(actor, event_prefix="event__"),
    ).distinct(), pk=pk)
    _manageable_event(actor, row.event_id)
    return row


class EventInviteListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=None, parameters=PAGE_PARAMETERS, responses={200: InviteListSerializer, **ERRORS})
    def get(self, request, pk):
        event = _manageable_event(request.user, pk)
        require_feature(event, "events.invites")
        return paginated(request, event.invites.order_by("id"), InviteSerializer)

    @extend_schema(tags=["Admin events"], request=InviteInputSerializer, responses={201: InviteSerializer, **ERRORS})
    def post(self, request, pk):
        event = _manageable_event(request.user, pk)
        serializer = InviteInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invite, code = create_invite(event, actor=request.user, **serializer.validated_data)
        return Response({**InviteSerializer(invite).data, "code": code}, status=201)


class EventInviteRevokeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=EmptyActionSerializer, responses={200: InviteSerializer, **ERRORS})
    def post(self, request, pk):
        invite = manageable_event_code(request.user, EventInvite.objects.all(), pk)
        serializer = EmptyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(InviteSerializer(revoke_invite(invite, actor=request.user)).data)
