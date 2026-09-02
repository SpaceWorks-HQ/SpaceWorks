from django.db.models import Count, Max, Sum

from apps.integrations.models import EmailLog, NotificationDeliveryLog, NotificationDestination
from apps.makerspaces.platform import module_enabled
from apps.notifications.models import Notification
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import apply_range, limited, report_spaces


FIELDS = (
    "module_key", "channel", "feature", "status", "delivery_count",
    "attempt_count", "destination_count", "success_rate_percent", "unread_count",
    "last_activity_at",
)


def build_communications_health(makerspace_id, *, limit=None, date_range=None):
    aggregate = makerspace_id is None
    records = []
    for space in report_spaces(makerspace_id):
        if module_enabled(space, "notifications"):
            _notification_rows(space.id, records, aggregate, date_range)
        if module_enabled(space, "email"):
            _email_rows(space.id, records, aggregate, date_range)
        for channel in ("telegram", "slack", "mattermost", "discord"):
            if module_enabled(space, channel):
                _channel_rows(space.id, channel, records, aggregate, date_range)
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, limited(records, limit))


def _notification_rows(space_id, records, aggregate, date_range):
    qs = apply_range(Notification.objects.filter(makerspace_id=space_id), "created_at", date_range)
    values = qs.aggregate(count=Count("id"), unread=Count("id", filter=_q(read_at__isnull=True)), last=Max("created_at"))
    _add(records, space_id, aggregate, module_key="notifications", channel="in_app", feature="inbox",
         status="generated", delivery_count=values["count"], attempt_count=values["count"],
         destination_count=1, success_rate_percent=100 if values["count"] else None,
         unread_count=values["unread"], last_activity_at=values["last"])


def _email_rows(space_id, records, aggregate, date_range):
    qs = apply_range(EmailLog.objects.filter(makerspace_id=space_id), "created_at", date_range)
    for row in qs.values("stream", "status").annotate(count=Count("id"), attempts=Sum("attempts"), last=Max("updated_at")):
        _add(records, space_id, aggregate, module_key="email", channel="email", feature=row["stream"] or "general",
             status=row["status"], delivery_count=row["count"], attempt_count=row["attempts"] or 0,
             destination_count=None, success_rate_percent=100 if row["status"] == EmailLog.Status.SENT else 0,
             unread_count=None, last_activity_at=row["last"])


def _channel_rows(space_id, channel, records, aggregate, date_range):
    destinations = NotificationDestination.objects.filter(makerspace_id=space_id, channel=channel, is_active=True).count()
    qs = apply_range(NotificationDeliveryLog.objects.filter(makerspace_id=space_id, channel=channel), "created_at", date_range)
    for row in qs.values("feature", "status").annotate(count=Count("id"), attempts=Sum("attempts"), last=Max("updated_at")):
        _add(records, space_id, aggregate, module_key=channel, channel=channel, feature=row["feature"],
             status=row["status"], delivery_count=row["count"], attempt_count=row["attempts"] or 0,
             destination_count=destinations, success_rate_percent=100 if row["status"] == "sent" else 0,
             unread_count=None, last_activity_at=row["last"])


def _add(records, space_id, aggregate, **values):
    row = {field: values.get(field) for field in FIELDS}
    if aggregate:
        row["makerspace_id"] = space_id
    records.append(row)


def _q(**kwargs):
    from django.db.models import Q
    return Q(**kwargs)
