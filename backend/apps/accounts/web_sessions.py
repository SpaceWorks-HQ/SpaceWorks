"""Revocable browser sessions backed by SimpleJWT's existing token ledger.

A session marker has an empty token body and a ``session:`` JTI, so it is never
a refresh credential. Rotating refresh credentials share its ``sid`` claim;
blacklisting one consumed refresh must not revoke that stable session marker.
"""

import uuid
from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import UntypedToken


def create_session(user, refresh):
    sid = f"session:{uuid.uuid4()}"
    OutstandingToken.objects.create(
        user=user, jti=sid, token="", created_at=timezone.now(),
        expires_at=datetime.fromtimestamp(refresh["exp"], tz=UTC),
    )
    refresh["sid"] = sid


def validate_session(user, token, *, lock=False):
    # Sessions issued before this feature remain usable for the existing JWT
    # lifetime; they acquire a marker on their next successful refresh.
    sid = token.get("sid")
    if not sid:
        return None
    rows = OutstandingToken.objects
    if lock:
        rows = rows.select_for_update()
    row = rows.filter(user=user, jti=sid, token="", expires_at__gt=timezone.now()).first()
    if row is None or BlacklistedToken.objects.filter(token=row).exists():
        raise AuthenticationFailed("This session has been revoked.", code="session_revoked")
    return row


def extend_session(user, refresh):
    row = validate_session(user, refresh, lock=True)
    if row is None:
        create_session(user, refresh)
    else:
        row.expires_at = datetime.fromtimestamp(refresh["exp"], tz=UTC)
        row.save(update_fields=["expires_at"])


def active_sessions(user):
    return OutstandingToken.objects.filter(
        user=user, token="", jti__startswith="session:",
        expires_at__gt=timezone.now(), blacklistedtoken__isnull=True,
    ).order_by("-created_at", "-pk")


def legacy_sessions(user):
    """Refresh credentials predating sid; native grant families have their own UI."""
    from apps.accounts.models_devices import DeviceRefreshToken
    rows = OutstandingToken.objects.filter(user=user, expires_at__gt=timezone.now(),
                                           blacklistedtoken__isnull=True).exclude(token="")
    rows = rows.exclude(jti__in=DeviceRefreshToken.objects.values("jti"))
    for row in rows.order_by("-created_at", "-pk"):
        try:
            token = UntypedToken(row.token)
        except TokenError:
            continue
        if token.get("token_type") == "refresh" and not token.get("sid"):
            yield row


@transaction.atomic
def revoke_session(user, sid):
    row = OutstandingToken.objects.select_for_update().filter(user=user, jti=sid, token="").first()
    if row is None:
        raise NotFound("Session not found.")
    BlacklistedToken.objects.get_or_create(token=row)
    return row


@transaction.atomic
def revoke_legacy_session(user, jti):
    allowed_ids = {row.pk for row in legacy_sessions(user)}
    row = OutstandingToken.objects.select_for_update().filter(user=user, jti=jti, pk__in=allowed_ids).first()
    if row is None:
        raise NotFound("Session not found.")
    BlacklistedToken.objects.get_or_create(token=row)
    return row
