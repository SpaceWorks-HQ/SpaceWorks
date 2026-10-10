"""Delivery-time preference and suppression checks plus RFC 8058 headers."""

from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.utils.crypto import salted_hmac

from apps.accounts import rbac
from apps.integrations.models_suppression import EmailSuppression

TOKEN_SALT = "spaceworks.email.unsubscribe.v1"
TOKEN_MAX_AGE = 60 * 60 * 24 * 365


def address_hash(makerspace_id, address):
    return salted_hmac(
        "spaceworks.email.suppression.v1",
        f"{makerspace_id}:{address.strip().casefold()}", algorithm="sha256",
    ).hexdigest()


def suppressed(makerspace, address):
    if makerspace is None:
        return EmailSuppression.objects.filter(
            makerspace__isnull=True, address_hash=address_hash(None, address),
        ).exists()
    return rbac.scope_notification_policy(
        EmailSuppression.objects.all(), makerspace_id=makerspace.pk,
    ).filter(address_hash=address_hash(makerspace.pk, address)).exists()


def blocked_reason(makerspace, address, *, user_id=None, feature="", stream="", event=""):
    # Bounce/complaint blocks even safety mail: retrying a known dead address cannot deliver it.
    if suppressed(makerspace, address):
        return "email_address_suppressed"
    if makerspace is not None and user_id:
        from apps.notifications.preferences import STREAM_FEATURES, personal_enabled

        family = feature or STREAM_FEATURES.get(stream, stream)
        if not personal_enabled(makerspace, user_id, family, "email", stream=stream, event=event):
            return "email_member_opted_out"
    return ""


def unsubscribe_token(makerspace_id, user_id, feature):
    return signing.dumps({"space": makerspace_id, "user": user_id, "feature": feature}, salt=TOKEN_SALT)


def decode_unsubscribe(token):
    from apps.integrations.notification_catalog import FEATURE_EVENTS

    data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    if not isinstance(data, dict) or set(data) != {"space", "user", "feature"}:
        raise signing.BadSignature("Invalid unsubscribe token.")
    if type(data["space"]) is not int or type(data["user"]) is not int or min(data["space"], data["user"]) < 1:
        raise signing.BadSignature("Invalid unsubscribe identity.")
    if data["feature"] not in FEATURE_EVENTS:
        raise signing.BadSignature("Invalid unsubscribe family.")
    return data


def unsubscribe_headers(log):
    from apps.makerspaces.platform import feature_enabled
    from apps.notifications.preferences import mandatory_email

    if not log.makerspace_id or not log.recipient_id or not log.feature or mandatory_email(log.stream, log.event):
        return {}
    if not feature_enabled(log.makerspace, "notifications.member_preferences"):
        return {}
    base = settings.PUBLIC_APP_BASE_URL.rstrip("/")
    # RFC 8058 requires HTTPS. Do not invent an origin or use request Host headers.
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc:
        return {}
    token = unsubscribe_token(log.makerspace_id, log.recipient_id, log.feature)
    url = f"{base}/api/v1/notifications/unsubscribe/{token}"
    return {"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
