import logging
import json
from urllib import request as urllib_request

from django.conf import settings

from apps.integrations.notification_enums import trim_for_channel

logger = logging.getLogger(__name__)


class TelegramDeliveryError(Exception):
    pass


def resolve_bot_token(makerspace):
    """The bot a makerspace posts as: its own token, else the deployment's.

    Destinations deliberately do NOT override this (D16). The original reason was
    inbound: accept/reject buttons posted back to one registered webhook authenticated by
    a single `TELEGRAM_WEBHOOK_SECRET`, so a second bot's callbacks could not be
    authenticated or routed. **Those buttons are gone** — chat is no longer an action
    surface — but the rule stands on its outbound half: one bot identity per makerspace
    across all of its rooms is what makes per-machine rooms read as one sender rather
    than as a handful of unrelated bots, and it keeps the token surface to one secret.
    """
    token = (
        makerspace.get_telegram_bot_token()
        if hasattr(makerspace, "get_telegram_bot_token")
        else getattr(makerspace, "telegram_bot_token", "")
    )
    return token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")


def resolve_chat_id(makerspace, destination=None):
    if destination is not None:
        return destination.telegram_chat_id
    return getattr(makerspace, "telegram_group_chat_id", "")


def send_message(makerspace, text, destination=None):
    token = resolve_bot_token(makerspace)
    chat_id = resolve_chat_id(makerspace, destination)
    if not token or not chat_id:
        logger.info(
            "Telegram delivery skipped.",
            extra={
                "makerspace_id": makerspace.pk,
                "configured": bool(token and chat_id),
                "destination_id": getattr(destination, "pk", None),
            },
        )
        return False

    base_url = getattr(settings, "TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")
    # No `reply_markup`: Telegram is a notification channel here, and an inline keyboard
    # is by definition an action surface. The accept/reject buttons were removed with the
    # callback route that served them.
    payload = {"chat_id": chat_id, "text": trim_for_channel("telegram", text)}
    try:
        body = json.dumps(payload).encode()
        req = urllib_request.Request(
            f"{base_url}/bot{token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                raise TelegramDeliveryError("Telegram delivery failed.")
    except Exception as exc:
        logger.warning(
            "Telegram delivery failed.",
            extra={
                "makerspace_id": makerspace.pk,
                "destination_id": getattr(destination, "pk", None),
            },
            exc_info=exc,
        )
        raise TelegramDeliveryError("Telegram delivery failed.") from exc
    return True
