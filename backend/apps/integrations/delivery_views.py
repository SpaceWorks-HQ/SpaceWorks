from django.db import transaction
from django.db.models import CharField, IntegerField, Value
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.integrations.delivery_serializers import (
    DeliveryFilters, DeliveryPageSerializer, DeliverySerializer, DeliveryTestResultSerializer,
    DeliveryTestSerializer, RetrySerializer,
)
from apps.integrations.delivery_services import retry_delivery
from apps.integrations.dispatch import dispatch_email, email_module_blocks
from apps.integrations.dispatch_channels import channel_module_blocks
from apps.integrations.models import EmailLog, NotificationDeliveryLog
from apps.integrations.models_destinations import NotificationDestination
from apps.makerspaces.servability import servable_queryset
from apps.openapi_errors import errors

FIELDS = ("id", "kind", "channel", "feature", "event", "destination_id", "destination_label",
          "status", "error", "attempts", "retry_generation", "created_at", "sent_at")


def staff_space(user, makerspace_id):
    return get_object_or_404(rbac.scope_by_action(
        user, rbac.Action.MANAGE_MAKERSPACE, servable_queryset(), field="pk",
    ), pk=makerspace_id)


def channel_rows(user, space):
    return rbac.scope_by_action(user, rbac.Action.MANAGE_MAKERSPACE,
                               NotificationDeliveryLog.objects.all()).filter(makerspace=space)


def email_rows(user, space):
    return rbac.scope_by_action(user, rbac.Action.MANAGE_MAKERSPACE,
                               EmailLog.objects.all()).filter(makerspace=space)


def row_data(log):
    return {field: ("email" if isinstance(log, EmailLog) else "channel") if field == "kind"
            else getattr(log, field, "email" if field == "channel" else None if field == "destination_id" else "Email")
            for field in FIELDS}


class DeliveryLogListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Notification delivery"], parameters=[
        OpenApiParameter("page", int), OpenApiParameter("channel", str),
        OpenApiParameter("status", str), OpenApiParameter("feature", str),
        OpenApiParameter("event", str), OpenApiParameter("destination", int),
    ], responses={200: DeliveryPageSerializer, **errors(400, 401, 403, 404)})
    def get(self, request, makerspace_id):
        space = staff_space(request.user, makerspace_id)
        filters = DeliveryFilters(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        mail, channel = email_rows(request.user, space), channel_rows(request.user, space)
        for key in ("status", "feature", "event"):
            if key in data:
                mail, channel = mail.filter(**{key: data[key]}), channel.filter(**{key: data[key]})
        if "destination" in data:
            mail = mail.none()
            channel = channel.filter(destination_id=data["destination"])
        if "channel" in data:
            if data["channel"] == "email":
                channel = channel.none()
            else:
                mail = mail.none()
                channel = channel.filter(channel=data["channel"])
        mail = mail.annotate(kind=Value("email", output_field=CharField()),
                             channel=Value("email", output_field=CharField()),
                             destination_id=Value(None, output_field=IntegerField()),
                             destination_label=Value("Email", output_field=CharField()))
        channel = channel.annotate(kind=Value("channel", output_field=CharField()))
        rows = mail.order_by().values(*FIELDS).union(channel.order_by().values(*FIELDS), all=True).order_by("-created_at", "-id")
        paginator = PageNumberPagination()
        paginator.page_size = 24
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(DeliverySerializer(page, many=True).data)


class DeliveryLogRetryView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Notification delivery"], request=RetrySerializer,
                   responses={200: DeliverySerializer, **errors(400, 401, 403, 404, 423, 503)})
    def post(self, request, makerspace_id, kind, pk):
        space = staff_space(request.user, makerspace_id)
        if kind not in ("email", "channel"):
            raise ValidationError({"kind": "Expected email or channel."})
        rows = email_rows(request.user, space) if kind == "email" else channel_rows(request.user, space)
        log = get_object_or_404(rows, pk=pk)
        blocked = email_module_blocks(space, log.stream, log.event) if kind == "email" else channel_module_blocks(space, log.channel)
        if blocked:
            raise ValidationError({"module": "This delivery channel is disabled."})
        serializer = RetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = retry_delivery(request.user, log, expected_generation=serializer.validated_data["generation"])
        return Response(DeliverySerializer(row_data(log)).data)


class DeliveryTestView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Notification delivery"], request=DeliveryTestSerializer,
                   responses={200: DeliveryTestResultSerializer, **errors(400, 401, 403, 404, 423, 503)})
    def post(self, request, makerspace_id):
        space = staff_space(request.user, makerspace_id)
        serializer = DeliveryTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        destination_id = serializer.validated_data.get("destination_id")
        text = "SpaceWorks notification delivery test. No member data is included."
        with transaction.atomic():
            if destination_id:
                destination = get_object_or_404(rbac.scope_by_action(
                    request.user, rbac.Action.MANAGE_MAKERSPACE, NotificationDestination.objects.all(),
                ), pk=destination_id, makerspace=space, is_active=True)
                if channel_module_blocks(space, destination.channel):
                    raise ValidationError({"module": "The destination channel is disabled."})
                from apps.integrations.delivery_tests import queue_destination_test
                log = queue_destination_test(space, destination, text)
                kind = "channel"
            else:
                if not request.user.email or email_module_blocks(space, "test", "delivery_test"):
                    raise ValidationError({"email": "Email is disabled or your account has no email address."})
                log = dispatch_email(makerspace=space, to_email=request.user.email,
                                     recipient_id=request.user.pk, subject="SpaceWorks delivery test",
                                     text_body=text, stream="test", event="delivery_test", audience="staff")
                kind = "email"
            audit.record(request.user, "notification.test_sent", makerspace=space, target=space,
                         meta={"channel": getattr(log, "channel", "email")})
        return Response({"kind": kind, "id": log.pk, "status": log.status})
