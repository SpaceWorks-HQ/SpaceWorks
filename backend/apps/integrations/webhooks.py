import http.client
import json
import logging
import socket
from urllib.parse import urljoin

from apps.integrations.notification_enums import trim_for_channel
from apps.integrations.webhook_validation import (
    ResolvedAddress,
    ResolvedWebhookTarget,
    resolve_webhook_target,
)

logger = logging.getLogger(__name__)

# Slack and Mattermost share a payload shape ({"text": ...}); Discord names the same
# field "content" and ignores "text" entirely.
_BODY_KEY = {"slack": "text", "mattermost": "text", "discord": "content"}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 3
_TIMEOUT_SECONDS = 5


class WebhookDeliveryError(Exception):
    pass


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS to one resolved IP, while authenticating the original DNS hostname."""

    def __init__(self, target: ResolvedWebhookTarget, address: ResolvedAddress):
        super().__init__(target.hostname, target.port, timeout=_TIMEOUT_SECONDS)
        self._pinned_address = address

    def connect(self):
        address = self._pinned_address
        raw_socket = socket.socket(address.family, address.socktype, address.proto)
        raw_socket.settimeout(self.timeout)
        try:
            raw_socket.connect(address.sockaddr)
            # `self.host` remains the URL hostname, so SNI and certificate hostname
            # verification do not accidentally switch to the pinned IP literal.
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


def _resolve_url(makerspace, channel):
    if channel == "slack":
        return makerspace.get_slack_webhook_url()
    if channel == "mattermost":
        return makerspace.get_mattermost_webhook_url()
    return makerspace.get_discord_webhook_url()


def _post_to_target(
    target: ResolvedWebhookTarget, payload: bytes
) -> tuple[int, str | None]:
    last_error = None
    for address in target.addresses:
        connection = _PinnedHTTPSConnection(target, address)
        try:
            connection.request(
                "POST",
                target.request_target,
                body=payload,
                headers={
                    "Content-Type": "application/json",
                    "Host": target.host_header,
                },
            )
            response = connection.getresponse()
            return response.status, response.getheader("Location")
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()
    if last_error is not None:
        raise last_error
    raise WebhookDeliveryError("Webhook delivery failed.")


def _deliver(url: str, payload: bytes) -> None:
    current_url = url
    for hop in range(_MAX_REDIRECTS + 1):
        # Resolve at send time even though the URL was validated when saved. The returned
        # socket addresses are the exact ones used by `_PinnedHTTPSConnection`.
        target = resolve_webhook_target(current_url)
        status, location = _post_to_target(target, payload)
        if status in _REDIRECT_STATUSES:
            if hop == _MAX_REDIRECTS or not location:
                raise WebhookDeliveryError("Webhook redirect was refused.")
            current_url = urljoin(current_url, location)
            continue
        if not 200 <= status < 300:
            raise WebhookDeliveryError("Webhook delivery failed.")
        return
    raise WebhookDeliveryError("Webhook redirect was refused.")


def send_webhook(makerspace, *, channel: str, text: str, destination=None) -> bool:
    """Post one message after validating and pinning every destination and redirect."""
    if channel not in _BODY_KEY:
        raise ValueError(f"Unsupported webhook channel: {channel}")

    url = destination.get_webhook_url() if destination is not None else _resolve_url(
        makerspace, channel
    )
    if not url:
        return False

    payload = json.dumps(
        {_BODY_KEY[channel]: trim_for_channel(channel, text)}
    ).encode("utf-8")
    try:
        _deliver(url, payload)
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
