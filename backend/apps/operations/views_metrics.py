"""Prometheus text exposition for the deployment.

Deliberately dependency-free: the exposition format is a handful of lines and pulling in a
metrics library for six gauges would add a process-wide registry the tests then have to
reset. Everything here is a point-in-time read of state the platform already keeps.

Access is a static bearer token. With no token configured the route answers 404, not 401,
so an unconfigured deployment does not even advertise that the surface exists.
"""
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Max, Sum
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape_label(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Exposition:
    def __init__(self):
        self.lines = []

    def gauge(self, name, help_text, samples):
        """``samples`` is an iterable of (labels dict, value)."""
        self.lines.append(f"# HELP {name} {help_text}")
        self.lines.append(f"# TYPE {name} gauge")
        for labels, value in samples:
            rendered = ",".join(
                f'{key}="{_escape_label(val)}"' for key, val in sorted(labels.items())
            )
            suffix = f"{{{rendered}}}" if rendered else ""
            self.lines.append(f"{name}{suffix} {value}")

    def render(self):
        return "\n".join(self.lines) + "\n"


def _celery_queue_lengths():
    """Queue depth from the broker; empty when the deployment runs tasks eagerly."""
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return []
    try:
        import redis
    except ImportError:  # pragma: no cover - redis is a hard requirement in practice
        return []
    queue = getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", None) or "celery"
    try:
        client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=1)
        return [({"queue": queue}, int(client.llen(queue)))]
    except Exception:  # broker unreachable: report nothing rather than fail the scrape
        return []


def _collect():
    from apps.evidence.retention_models import EvidenceObjectRetentionState
    from apps.hardware_requests.models import HardwareRequest
    from apps.integrations.models import EmailLog, NotificationDeliveryLog
    from apps.makerspaces.models import Makerspace

    since = timezone.now() - timedelta(hours=1)
    out = _Exposition()

    out.gauge(
        "spaceworks_celery_queue_length",
        "Messages waiting in the Celery broker queue.",
        _celery_queue_lengths(),
    )
    out.gauge(
        "spaceworks_hardware_requests",
        "Hardware requests by workflow status.",
        [
            ({"status": row["status"]}, row["n"])
            for row in HardwareRequest.objects.values("status").annotate(n=Count("id"))
        ],
    )
    deliveries = [
        ({"channel": row["channel"], "status": row["status"]}, row["n"])
        for row in NotificationDeliveryLog.objects.filter(created_at__gte=since)
        .values("channel", "status")
        .annotate(n=Count("id"))
    ]
    deliveries += [
        ({"channel": "email", "status": row["status"]}, row["n"])
        for row in EmailLog.objects.filter(created_at__gte=since)
        .values("status")
        .annotate(n=Count("id"))
    ]
    out.gauge(
        "spaceworks_notification_deliveries_last_hour",
        "Notification delivery attempts in the last hour by channel and status.",
        deliveries,
    )
    out.gauge(
        "spaceworks_storage_bytes_used",
        "Managed object storage accounted to each makerspace.",
        [
            ({"makerspace_id": row["id"]}, row["storage_bytes_used"])
            for row in Makerspace.objects.values("id", "storage_bytes_used")
        ],
    )
    out.gauge(
        "spaceworks_storage_bytes_used_total",
        "Managed object storage accounted across all makerspaces.",
        [({}, Makerspace.objects.aggregate(total=Sum("storage_bytes_used"))["total"] or 0)],
    )
    out.gauge(
        "spaceworks_evidence_retention_states",
        "Evidence photos by object-retention state.",
        [
            ({"status": row["status"]}, row["n"])
            for row in EvidenceObjectRetentionState.objects.values("status").annotate(n=Count("id"))
        ],
    )
    last_expiry = EvidenceObjectRetentionState.objects.aggregate(
        latest=Max("object_expired_at")
    )["latest"]
    out.gauge(
        "spaceworks_evidence_retention_last_expiry_timestamp_seconds",
        "Unix time of the most recent evidence object expiry (0 when none).",
        [({}, int(last_expiry.timestamp()) if last_expiry else 0)],
    )
    return out.render()


def _presented_token(request):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return request.headers.get("X-Metrics-Token", "")


class MetricsView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        tags=["Health"],
        summary="Prometheus metrics",
        description=(
            "Prometheus text exposition of queue depth, request states, notification "
            "delivery outcomes, storage accounting and evidence retention. Requires the "
            "deployment's METRICS_TOKEN as a bearer token; 404 when no token is configured."
        ),
        request=None,
        responses={(200, "text/plain"): OpenApiTypes.STR, 401: None, 404: None},
    )
    def get(self, request, *args, **kwargs):
        expected = getattr(settings, "METRICS_TOKEN", "")
        if not expected:
            raise Http404
        if not constant_time_compare(_presented_token(request), expected):
            response = HttpResponse("unauthorized\n", status=401, content_type="text/plain")
            response["WWW-Authenticate"] = "Bearer"
            return response
        return HttpResponse(_collect(), content_type=CONTENT_TYPE)
