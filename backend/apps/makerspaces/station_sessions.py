from datetime import datetime
from uuid import UUID

from django.core import signing
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.makerspaces.models_stations import StationCredential


def sign_session(*, public_token, version, session_id, expires_at, salt):
    return signing.dumps(
        {
            "public_token": str(public_token),
            "version": version,
            "session_id": str(session_id),
            "expires_at": expires_at.isoformat(),
        },
        salt=salt,
        compress=True,
    )


def read_session(value, *, salt):
    return signing.loads(value, salt=salt)


def resolve_session(
    public_token, cookie_value, *, salt, refusal, expiry_policy=None, with_expiry=False,
):
    """Resolve a signed Station cookie to its live credential.

    ``with_expiry`` appends the parsed signed expiry so kiosk callers can clamp leases
    and idle state to it; event-station callers keep the original three-tuple.
    """
    try:
        token = UUID(str(public_token))
        payload = read_session(cookie_value, salt=salt)
        session_id = UUID(payload["session_id"])
        expires_at = datetime.fromisoformat(payload["expires_at"])
    except Exception:
        raise PermissionDenied(refusal) from None
    credential = StationCredential.objects.select_related("station__makerspace").filter(
        public_token=token,
        is_enabled=True,
        version=payload.get("version"),
    ).first()
    expired = (
        expiry_policy(expires_at)
        if expiry_policy is not None
        else timezone.now() > expires_at
    )
    if credential is None or payload.get("public_token") != str(token) or expired:
        raise PermissionDenied(refusal)
    if with_expiry:
        return credential.station, credential, session_id, expires_at
    return credential.station, credential, session_id
