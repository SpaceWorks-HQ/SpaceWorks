from django.conf import settings
from django.http import Http404
from django.utils.crypto import constant_time_compare
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hardware_requests.services_return_reminders import run_return_reminders


ReturnReminderCronResponseSerializer = inline_serializer(
    name="ReturnReminderCronResponse",
    fields={
        "sent": serializers.IntegerField(),
        "skipped": serializers.IntegerField(),
    },
)


class ReturnReminderCronView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        tags=["Health"],
        auth=[],
        request=None,
        responses={
            200: OpenApiResponse(
                response=ReturnReminderCronResponseSerializer,
                description="Return reminder run result.",
            ),
            403: OpenApiResponse(description="Invalid cron secret."),
            404: OpenApiResponse(description="Cron endpoint is not configured."),
        },
    )
    def post(self, request):
        secret = settings.CRON_SECRET
        if not secret:
            raise Http404()
        provided = request.headers.get("X-Cron-Secret", "")
        # constant_time_compare encodes both sides, so a non-ASCII header is a plain
        # mismatch (403) rather than the TypeError -> 500 that compare_digest(str, str)
        # raises on any character outside ASCII.
        if not constant_time_compare(provided, secret):
            return Response(status=403)
        result = run_return_reminders()
        return Response(result, status=200)
