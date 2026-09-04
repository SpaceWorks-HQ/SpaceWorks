from uuid import uuid4

from django.core import signing
from django.utils import timezone

from apps.events.checkin_policy import roster_expiry, window_for
from apps.makerspaces.station_sessions import read_session, sign_session


LEASE_SALT = "spaceworks.events.checkin-lease.v1"
STATION_COOKIE_SALT = "spaceworks.events.station-cookie.v1"


def build_lease(event, *, kind, actor_id=None, session_id=None, station_version=None):
    now = timezone.now()
    window = window_for(event)
    session_id = session_id or uuid4()
    payload = {
        "kind": kind,
        "lease_id": str(session_id),
        "event_id": event.pk,
        "makerspace_id": event.makerspace_id,
        "actor_id": actor_id,
        "station_version": station_version,
        "issued_at": now.isoformat(),
        "expires_at": roster_expiry(event, now=now).isoformat(),
        "scan_opens_at": window.opens_at.isoformat(),
        "scan_closes_at": window.closes_at.isoformat(),
        "sync_deadline": window.sync_deadline.isoformat(),
    }
    return payload, signing.dumps(payload, salt=LEASE_SALT, compress=True)


def read_lease(token):
    return signing.loads(token, salt=LEASE_SALT)


def sign_station_cookie(*, public_token, version, session_id, expires_at):
    return sign_session(
        public_token=public_token,
        version=version,
        session_id=session_id,
        expires_at=expires_at,
        salt=STATION_COOKIE_SALT,
    )


def read_station_cookie(value):
    return read_session(value, salt=STATION_COOKIE_SALT)
