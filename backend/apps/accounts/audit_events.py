import hashlib
import hmac

from django.conf import settings

from rest_framework_simplejwt.exceptions import TokenError
from apps.accounts.models import User
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.audit import services as audit


def fingerprint(value):
    value = str(value or "").strip().lower()
    if not value:
        return ""
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def record_auth_event(actor, action, *, target=None, meta=None):
    clean_meta = {
        key: value for key, value in (meta or {}).items() if value not in (None, "")
    }
    return audit.record(actor, action, target=target, meta=clean_meta)


def record_refresh_rejected(cookie, reason):
    """Audit one rejected refresh attempt, resolving the actor from the presented token.

    The three rejection paths in RefreshView all need the same actor lookup + event, and
    the actor can only come from the token itself (the request is unauthenticated).
    """
    actor = user_from_refresh_token(cookie)
    record_auth_event(
        actor, "auth.refresh_rejected", target=actor, meta={"reason": reason}
    )


def user_from_refresh_token(token_str):
    if not token_str:
        return None
    try:
        from apps.accounts.claim_tokens import claim_user_from_refresh

        claim_user = claim_user_from_refresh(token_str)
        if claim_user is not None:
            return claim_user
    except TokenError:
        pass
    try:
        token = SpaceWorksRefreshToken(token_str)
    except TokenError:
        return None
    return User.objects.filter(pk=token.get("user_id")).first()
