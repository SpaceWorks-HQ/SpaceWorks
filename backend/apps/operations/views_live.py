"""Server-Sent Events stream of live-update hints.

One long-lived GET per browser session. The client is told *that* something changed and
which kind of thing; it refetches through the ordinary endpoints, so authorization is never
re-implemented here — the stream only decides which channels a session may subscribe to,
using the same RBAC scoping as every other query.

Served by the dedicated ``live`` gunicorn service (thread workers, no request timeout, no
worker recycling); see docker-compose*.yml and frontend/nginx.conf.
"""
import logging
import time

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.makerspaces.models import Makerspace
from apps.operations import live

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 25
MAX_STREAM_SECONDS = 60 * 60  # the client reconnects; bounded so a worker thread is never held forever


def subscribed_channels(user):
    """Every channel this session may hear: its own user channel plus each visible makerspace."""
    channels = [live.user_channel(user.pk)]
    # scope_by_makerspace is the one authority: superadmin => every makerspace, staff => their
    # memberships (archived/hidden excluded), a plain member => none.
    scoped = rbac.scope_by_makerspace(user, Makerspace.objects.all(), makerspace_field="pk")
    channels.extend(
        live.makerspace_channel(pk) for pk in scoped.order_by("pk").values_list("pk", flat=True)
    )
    return channels


def _event_stream(pubsub, deadline):
    yield "retry: 5000\n\n"
    last_beat = time.monotonic()
    while time.monotonic() < deadline:
        message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if message and message.get("type") == "message":
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8", "replace")
            yield f"event: change\ndata: {data}\n\n"
        if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
            yield ": keep-alive\n\n"
            last_beat = time.monotonic()


class EventStreamRenderer(BaseRenderer):
    """Lets DRF's content negotiation accept ``Accept: text/event-stream``.

    Without it the browser's EventSource-style request is refused with 406 before ``get``
    runs. The body itself is a StreamingHttpResponse, so ``render`` only ever sees the
    error payloads, which are returned as plain JsonResponse objects instead.
    """

    media_type = "text/event-stream"
    format = "sse"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return b"" if data is None else str(data).encode("utf-8")


def _unavailable(detail):
    return JsonResponse({"detail": detail}, status=503)


class LiveStreamView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = []
    renderer_classes = [EventStreamRenderer, JSONRenderer]

    @extend_schema(
        tags=["Health"],
        summary="Live update stream (Server-Sent Events)",
        description=(
            "text/event-stream of `change` events `{kind, makerspace_id, target_type, target_id, "
            "actor_id, ts}` for every makerspace the session may see. Clients invalidate cached "
            "queries on an event and refetch; no tenant content travels on the stream. 503 when the "
            "deployment has no Redis."
        ),
        request=None,
        responses={(200, "text/event-stream"): OpenApiTypes.STR, 503: None},
    )
    def get(self, request, *args, **kwargs):
        client = live.redis_client()
        if client is None:
            return _unavailable("Live updates are not available on this deployment.")
        channels = subscribed_channels(request.user)
        try:
            pubsub = client.pubsub()
            pubsub.subscribe(*channels)
        except Exception:
            logger.warning("live_subscribe_failed", extra={"user_id": request.user.pk})
            return _unavailable("Live updates are temporarily unavailable.")
        deadline = time.monotonic() + getattr(settings, "LIVE_MAX_STREAM_SECONDS", MAX_STREAM_SECONDS)
        response = StreamingHttpResponse(
            _event_stream(pubsub, deadline), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
