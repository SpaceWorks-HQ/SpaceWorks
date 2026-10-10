from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.audit import services as audit
from apps.integrations.notification_catalog import FEATURE_EVENTS
from apps.notifications.access import personal_space
from apps.notifications.models_inbox import NotificationInboxRow
from apps.notifications.serializers_inbox import (
    CountSerializer, InboxPageSerializer, InboxSerializer, ReadAllSerializer,
)
from apps.openapi_errors import errors
from apps.tenant_migration.gate_runtime import tenant_write

ERRORS = errors(400, 401, 403, 404)
WRITE_ERRORS = errors(400, 401, 403, 404, 423, 503)


class InboxFilters(serializers.Serializer):
    unread = serializers.BooleanField(required=False, default=False)
    feature = serializers.ChoiceField(choices=tuple(FEATURE_EVENTS), required=False)


class InboxBase(APIView):
    permission_classes = [IsAuthenticated]

    def rows(self, request, makerspace_id):
        space = personal_space(request.user, makerspace_id)
        return space, rbac.scope_personal_notifications(
            request.user, NotificationInboxRow.objects.all(),
        ).filter(makerspace=space)


class InboxListView(InboxBase):
    @extend_schema(tags=["Personal notifications"], parameters=[
        OpenApiParameter("page", int), OpenApiParameter("unread", bool),
        OpenApiParameter("feature", str, enum=list(FEATURE_EVENTS)),
    ], responses={200: InboxPageSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        _, rows = self.rows(request, makerspace_id)
        filters = InboxFilters(data=request.query_params)
        filters.is_valid(raise_exception=True)
        if filters.validated_data["unread"]:
            rows = rows.filter(read_at__isnull=True)
        if filters.validated_data.get("feature"):
            rows = rows.filter(feature=filters.validated_data["feature"])
        paginator = PageNumberPagination()
        paginator.page_size = 24
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(InboxSerializer(page, many=True).data)


class InboxUnreadView(InboxBase):
    @extend_schema(tags=["Personal notifications"], responses={200: CountSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        _, rows = self.rows(request, makerspace_id)
        return Response({"count": rows.filter(read_at__isnull=True).count()})


class InboxReadView(InboxBase):
    @extend_schema(tags=["Personal notifications"], request=None,
                   responses={200: InboxSerializer, **WRITE_ERRORS})
    def post(self, request, makerspace_id, pk):
        space, rows = self.rows(request, makerspace_id)
        with tenant_write(space.pk):
            row = get_object_or_404(rows.select_for_update(), pk=pk)
            if row.read_at is None:
                row.read_at = timezone.now()
                row.save(update_fields=["read_at"])
                audit.record(request.user, "notification.inbox_read", makerspace=space, target=space)
        return Response(InboxSerializer(row).data)


class InboxReadAllView(InboxBase):
    @extend_schema(tags=["Personal notifications"], request=None,
                   responses={200: ReadAllSerializer, **WRITE_ERRORS})
    def post(self, request, makerspace_id):
        space, rows = self.rows(request, makerspace_id)
        with tenant_write(space.pk):
            count = rows.filter(read_at__isnull=True).update(read_at=timezone.now())
            audit.record(request.user, "notification.inbox_read_all", makerspace=space,
                         target=space, meta={"count": count})
        return Response({"updated": count})
