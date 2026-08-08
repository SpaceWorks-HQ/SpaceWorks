import json
import logging
from urllib import request as urllib_request

from apps.integrations.notification_enums import trim_for_channel

logger = logging.getLogger(__name__)

# Slack and Mattermost share a payload shape ({"text": ...}); Discord names the same
# field "content" and ignores "text" entirely -- posting Slack's body to a Discord
# webhook returns 400 with no message delivered. One mapping, not three senders.
_BODY_KEY = {"slack": "text", "mattermost": "text", "discord": "content"}


class WebhookDeliveryError(Exception):
    pass


def _resolve_url(makerspace, channel):
    if channel == "slack":
        return makerspace.get_slack_webhook_url()
    if channel == "mattermost":
        return makerspace.get_mattermost_webhook_url()
    return makerspace.get_discord_webhook_url()


def send_webhook(makerspace, *, channel: str, text: str, destination=None) -> bool:
    """Post one message. `destination=None` is the legacy makerspace-column path.

    Keeping the None branch is what lets a space with no destination rows behave exactly
    as it did before this model existed — see `destinations.resolve_destinations`.
    """
    if channel not in _BODY_KEY:
        raise ValueError(f"Unsupported webhook channel: {channel}")

    url = destination.get_webhook_url() if destination is not None else _resolve_url(
        makerspace, channel
    )
    if not url:
        return False

    text = trim_for_channel(channel, text)

    try:
        req = urllib_request.Request(
            url,
            data=json.dumps({_BODY_KEY[channel]: text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                raise WebhookDeliveryError("Webhook delivery failed.")
        return True
    except Exception as exc:
        logger.warning(
            "Webhook delivery failed.",
            extra={
                "makerspace_id": makerspace.pk,
                "channel": channel,
                "destination_id": getattr(destination, "pk", None),
            },
        )
        raise WebhookDeliveryError("Webhook delivery failed.") from exc
