"""Read the same counters and limits used by quota enforcement."""

from django.conf import settings
from django.utils import timezone

from apps.makerspaces import limits
from apps.makerspaces.limits_usage import _COUNTERS

COUNTER_APPS = {"events": "events", "bookings": "bookings"}


def usage_snapshot(makerspace):
    from apps.integrations.models import DailyNotificationCounter

    notifications = dict(DailyNotificationCounter.objects.filter(
        makerspace=makerspace, day=timezone.now().date(),
    ).values_list("channel", "count"))
    resources = []
    for key in sorted(limits.NUMERIC_LIMIT_KEYS):
        counter = _COUNTERS.get(key)
        if COUNTER_APPS.get(key) in settings.TOMBSTONED_APPS:
            used = None
        else:
            used = counter(makerspace) if counter else notifications.get(key, 0)
        limit = limits.resource_limit(makerspace, key)
        resources.append({
            "key": key, "label": limits.RESOURCE_LABELS[key],
            "used": used, "limit": limit,
            "unit": "bytes" if key == "storage" else "count",
        })
    return {
        "makerspace_id": makerspace.pk,
        "managed": not limits.is_self_host(),
        "resources": resources,
    }
