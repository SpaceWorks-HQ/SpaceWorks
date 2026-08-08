import json
import logging
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

# Slack and Mattermost share a payload shape ({"text": ...}); Discord names the same
# field "content" and ignores "text" entirely -- posting Slack's body to a Discord
# webhook returns 400 with no message delivered. One mapping, not three senders.
_BODY_KEY = {"slack": "text", "mattermost": "text", "discord": "content"}

# Discord truncates at 2000 characters and rejects anything longer outright, so a long
# alert would be dropped rather than clipped. Trim to fit and mark it.
_MAX_LENGTH = {"discord": 2000}


class WebhookDeliveryError(Exception):
    pass


def _resolve_url(makerspace, channel):
    if channel == "slack":
        return makerspace.get_slack_webhook_url()
    if channel == "mattermost":
        return makerspace.get_mattermost_webhook_url()
    return makerspace.get_discord_webhook_url()


def send_webhook(makerspace, *, channel: str, text: str) -> bool:
    if channel not in _BODY_KEY:
        raise ValueError(f"Unsupported webhook channel: {channel}")

    url = _resolve_url(makerspace, channel)
    if not url:
        return False

    limit = _MAX_LENGTH.get(channel)
    if limit is not None and len(text) > limit:
        text = text[: limit - 1] + "…"

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
            extra={"makerspace_id": makerspace.pk, "channel": channel},
        )
        raise WebhookDeliveryError("Webhook delivery failed.") from exc
