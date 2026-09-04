"""Post one plain-text message into ONE explicitly chosen room.

The lifecycle fan-out (`notify.notify_lifecycle`) resolves rooms from the notification
matrix and destination scopes. A scheduled report is different: the schedule names the
exact destination it should land in, so this sends to that row and nothing else. It keeps
every other rule the fan-out applies -- the channel's module gate, the credential check,
the daily quota, the same transports -- and returns `(ok, error_code)` instead of raising,
because the caller records the outcome on its own delivery row.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from apps.integrations.dispatch_channels import (
    _channel_configured,
    channel_module_blocks,
    sanitize_notification_error,
)
from apps.integrations.notification_enums import ChatNotificationChannel
from apps.makerspaces import limits

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DestinationEnvelope:
    """The log-shaped object `webhooks.send_signed_webhook` builds its JSON body from.

    A scheduled report is not a lifecycle notification, so no `NotificationDeliveryLog`
    row exists for it; the signed-webhook sender only reads these attributes.
    """

    pk: str
    makerspace_id: int
    destination: object
    feature: str
    event: str
    text_body: str
    payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=timezone.now)


def deliver_text_to_destination(
    makerspace, destination, *, text, feature, event, reference, payload=None
):
    """Send `text` to `destination`; returns (delivered, error_code)."""
    if destination.makerspace_id != makerspace.pk:
        return False, "notification_destination_foreign"
    if not destination.is_active:
        return False, "notification_destination_inactive"
    channel = destination.channel
    if channel not in ChatNotificationChannel.values:
        return False, "notification_channel_unsupported"
    if channel_module_blocks(makerspace, channel):
        return False, "notification_channel_module_disabled"
    if not _channel_configured(makerspace, channel, destination):
        return False, "notification_channel_not_configured"
    if not limits.reserve_notification_quota(makerspace, channel):
        return False, "notification_quota_exceeded"
    try:
        if channel == ChatNotificationChannel.TELEGRAM:
            from apps.integrations.telegram import send_message

            ok = send_message(makerspace, text, destination=destination)
        elif channel == ChatNotificationChannel.WEBHOOK:
            from apps.integrations.webhooks import send_signed_webhook

            ok = send_signed_webhook(DestinationEnvelope(
                pk=str(reference), makerspace_id=makerspace.pk, destination=destination,
                feature=feature, event=event, text_body=text, payload=dict(payload or {}),
            ))
        else:
            from apps.integrations.webhooks import send_webhook

            ok = send_webhook(makerspace, channel=channel, text=text, destination=destination)
    except Exception as exc:
        logger.warning(
            "destination_delivery_failed",
            extra={"makerspace_id": makerspace.pk, "destination_id": destination.pk, "channel": channel},
        )
        return False, sanitize_notification_error(exc)
    if ok is True:
        return True, ""
    return False, "notification_channel_not_configured"
