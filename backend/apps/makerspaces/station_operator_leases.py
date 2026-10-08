"""Human operator leases on a kiosk Station session (phase 9b).

A lease binds one normally authenticated User to one live Station session. Its token
is signed and names the row; the row carries no bearer material. Every use re-checks
the row, the Station binding, the credential version, the user's live state and RBAC
(local membership OR organization grant, via ``rbac.effective_actions``), the source
gate and the operation's capability conjunction. The stored action snapshot can only
narrow that live result, never widen it.
"""

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.makerspaces.models_station_leases import StationOperatorLease


LEASE_SALT = "spaceworks.kiosk.operator-lease.v1"
LEASE_HEADER = "X-Kiosk-Operator-Lease"
LEASE_REFUSAL = "Invalid operator lease."


def _lease_meta(lease, **extra):
    return {
        "station_id": lease.station_id,
        "station_session_id": str(lease.station_session_id),
        "station_version": lease.station_version,
        "operator_lease_id": str(lease.pk),
        **extra,
    }


def _user_usable(user):
    return bool(
        user is not None
        and user.is_authenticated
        and user.access_status == User.AccessStatus.ACTIVE
        and not getattr(user, "must_change_password", False)
    )


def live_actions(user, station):
    from apps.hardware_requests.kiosk_command_policy import lease_actions

    if not _user_usable(user):
        return []
    effective = rbac.effective_actions(user, station.makerspace_id)
    return lease_actions(station.makerspace, station.kind, effective)


def sign_lease(lease):
    return signing.dumps(
        {
            "lease_id": str(lease.pk),
            "station_id": lease.station_id,
            "session_id": str(lease.station_session_id),
            "version": lease.station_version,
        },
        salt=LEASE_SALT,
        compress=True,
    )


@transaction.atomic
def issue_lease(*, station, credential, session_id, session_expires_at, user):
    actions = live_actions(user, station)
    if not actions:
        raise PermissionDenied(LEASE_REFUSAL)
    now = timezone.now()
    expires_at = min(
        now + timedelta(seconds=settings.KIOSK_OPERATOR_LEASE_TTL_SECONDS),
        session_expires_at,
    )
    lease = StationOperatorLease.objects.create(
        makerspace_id=station.makerspace_id,
        station=station,
        actor=user,
        station_session_id=session_id,
        station_version=credential.version,
        allowed_actions=actions,
        issued_at=now,
        expires_at=expires_at,
    )
    audit.record(
        user, "kiosk.operator_lease_issued", makerspace=station.makerspace,
        target=station, meta=_lease_meta(lease, allowed_actions=actions),
    )
    return lease, sign_lease(lease)


def resolve_lease(token, *, station, credential, session_id, user):
    """Return the live lease for this exact request, or refuse uniformly."""
    try:
        payload = signing.loads(token or "", salt=LEASE_SALT)
        lease_id = UUID(payload["lease_id"])
    except Exception:
        raise PermissionDenied(LEASE_REFUSAL) from None
    lease = StationOperatorLease.objects.filter(pk=lease_id).first()
    now = timezone.now()
    valid = (
        lease is not None
        and lease.revoked_at is None
        and lease.expires_at > now
        and payload.get("station_id") == station.pk == lease.station_id
        and lease.makerspace_id == station.makerspace_id
        and payload.get("session_id") == str(session_id) == str(lease.station_session_id)
        and payload.get("version") == credential.version == lease.station_version
        and _user_usable(user)
        and lease.actor_id == user.pk
    )
    if not valid:
        raise PermissionDenied(LEASE_REFUSAL)
    return lease


def current_actions(lease, user, station):
    """The stored snapshot narrowed by the user's live authority right now."""
    return set(lease.allowed_actions) & set(live_actions(user, station))


@transaction.atomic
def revoke_lease(lease, *, user):
    updated = StationOperatorLease.objects.filter(
        pk=lease.pk, revoked_at__isnull=True
    ).update(revoked_at=timezone.now())
    if updated:
        audit.record(
            user, "kiosk.operator_lease_revoked", makerspace=lease.station.makerspace,
            target=lease.station, meta=_lease_meta(lease),
        )
    return bool(updated)
