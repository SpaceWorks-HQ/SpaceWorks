from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.integrations.models import EmailLog
from apps.integrations.services import EmailRetryError, retry_email_log
from apps.makerspaces.servability import servable_queryset


class EmailLogPagination(PageNumberPagination):
    page_size = 24


class EmailLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailLog
        fields = (
            "id",
            "to_email",
            "subject",
            "stream",
            "event",
            "audience",
            "status",
            "error",
            "attempts",
            "created_at",
            "sent_at",
        )
        read_only_fields = fields


@extend_schema(
    tags=["Email logs"],
    summary="List makerspace email delivery logs",
    parameters=[OpenApiParameter("status", str, OpenApiParameter.QUERY)],
    responses={
        200: EmailLogSerializer(many=True),
        400: OpenApiResponse(description="Invalid status filter."),
        404: OpenApiResponse(description="Makerspace not found."),
    },
)
class EmailLogListView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "head", "options"]
    pagination_class = EmailLogPagination

    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )
        queryset = EmailLog.objects.filter(makerspace=makerspace).order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            valid_statuses = {choice for choice, _ in EmailLog.Status.choices}
            if status_filter not in valid_statuses:
                return Response(
                    {"status": "Invalid status filter."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(status=status_filter)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = EmailLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


@extend_schema(
    tags=["Email logs"],
    summary="Retry a failed makerspace email",
    request=None,
    responses={
        200: EmailLogSerializer,
        400: OpenApiResponse(description="Email log cannot be retried."),
        404: OpenApiResponse(description="Email log not found."),
    },
)
class EmailLogRetryView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    def post(self, request, makerspace_id, pk, *args, **kwargs):
        queryset = rbac.scope_by_action(
            request.user,
            rbac.Action.MANAGE_MAKERSPACE,
            servable_queryset(EmailLog.objects.all(), relation="makerspace"),
            field="makerspace_id",
        )
        # The makerspace_id path segment gives the origin-scope guard tenant context
        # (so tenant-domain admins aren't 403'd); also pins the log to that makerspace.
        log = get_object_or_404(queryset, pk=pk, makerspace_id=makerspace_id)
        try:
            retry_email_log(request.user, log)
        except EmailRetryError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(EmailLogSerializer(log).data)
