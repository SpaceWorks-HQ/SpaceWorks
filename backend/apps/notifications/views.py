from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.machines import role_scope
from apps.makerspaces.guards import require_module
from apps.makerspaces.servability import servable_queryset
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer


class NotificationPagination(PageNumberPagination):
    page_size = 24


class NotificationUnreadCountSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class NotificationMarkAllReadSerializer(serializers.Serializer):
    updated = serializers.IntegerField()


NOTIFICATION_ERROR_RESPONSES = {
    400: OpenApiResponse(description="Notifications module is disabled."),
    403: OpenApiResponse(description="Permission denied."),
    404: OpenApiResponse(description="Not found."),
}


def _makerspace_for_manager(user, makerspace_id):
    makerspace = get_object_or_404(
        rbac.scope_by_makerspace(
            user,
            servable_queryset(),
            makerspace_field="id",
        ),
        pk=makerspace_id,
    )
    require_module(makerspace, "notifications")
    if _is_guest_only(user, makerspace.id):
        raise PermissionDenied()
    # A `Notification` carries no machine provenance, and `read_at` is makerspace-wide, so
    # one team's acknowledgement would silence the row for every other team. Rather than
    # give a per-type maintainer a feed they cannot be scoped to, the inbox is withheld
    # from them entirely -- an accepted cost: they rely on email/chat, where per-event
    # recipient rules already narrow by machine. Adding provenance and a per-recipient
    # read state is the alternative, and it is a larger change than this phase.
    if role_scope.is_machine_only(user, makerspace.id):
        raise PermissionDenied()
    if not (
        rbac.can(user, rbac.Action.VIEW_INVENTORY, makerspace.id)
        or rbac.can(user, rbac.Action.MANAGE_PRINTING, makerspace.id)
        or rbac.can(user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id)
    ):
        raise PermissionDenied()
    return makerspace


@extend_schema(tags=["Notifications"])
class NotificationListView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "head", "options"]
    pagination_class = NotificationPagination

    @extend_schema(
        summary="List makerspace notifications",
        parameters=[
            OpenApiParameter(
                "unread",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                description="When true, return only unread notifications.",
            ),
            OpenApiParameter("page", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        responses={200: NotificationSerializer(many=True), **NOTIFICATION_ERROR_RESPONSES},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _makerspace_for_manager(request.user, makerspace_id)
        queryset = Notification.objects.filter(makerspace=makerspace).order_by("-created_at")
        if request.query_params.get("unread") == "true":
            queryset = queryset.filter(read_at__isnull=True)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = NotificationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


@extend_schema(tags=["Notifications"])
class NotificationUnreadCountView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        summary="Get unread makerspace notification count",
        responses={
            200: NotificationUnreadCountSerializer,
            **NOTIFICATION_ERROR_RESPONSES,
        },
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _makerspace_for_manager(request.user, makerspace_id)
        count = Notification.objects.filter(
            makerspace=makerspace,
            read_at__isnull=True,
        ).count()
        return Response({"count": count})


@extend_schema(tags=["Notifications"])
class NotificationMarkReadView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(
        summary="Mark a makerspace notification read",
        request=None,
        responses={200: NotificationSerializer, **NOTIFICATION_ERROR_RESPONSES},
    )
    def post(self, request, makerspace_id, pk, *args, **kwargs):
        makerspace = _makerspace_for_manager(request.user, makerspace_id)
        notification = get_object_or_404(Notification, pk=pk, makerspace=makerspace)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)


@extend_schema(tags=["Notifications"])
class NotificationMarkAllReadView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(
        summary="Mark all makerspace notifications read",
        request=None,
        responses={
            200: NotificationMarkAllReadSerializer,
            **NOTIFICATION_ERROR_RESPONSES,
        },
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = _makerspace_for_manager(request.user, makerspace_id)
        updated = Notification.objects.filter(
            makerspace=makerspace,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response({"updated": updated})

def _is_guest_only(user, makerspace_id):
    return rbac.is_handout_only(user, makerspace_id)
