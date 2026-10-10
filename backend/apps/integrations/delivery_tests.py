from django.db import transaction

from apps.integrations.dispatch_channels import _channel_configured, _enqueue_notification
from apps.integrations.models import NotificationDeliveryLog
from apps.makerspaces import limits


def queue_destination_test(space, destination, text):
    configured = _channel_configured(space, destination.channel, destination)
    allowed = configured and limits.reserve_notification_quota(space, destination.channel)
    log = NotificationDeliveryLog.objects.create(
        makerspace=space, destination=destination, destination_label=destination.label,
        channel=destination.channel, feature="api_access", event="delivery_test", text_body=text,
        status="pending" if allowed else "failed",
        error="" if allowed else "notification_channel_not_configured" if not configured else "notification_quota_exceeded",
    )
    if allowed:
        transaction.on_commit(lambda: _enqueue_notification(log.pk), robust=True)
    return log
