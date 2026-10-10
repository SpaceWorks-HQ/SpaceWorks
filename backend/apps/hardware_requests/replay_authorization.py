"""Session/lease bearer authentication plus live, operation-specific human RBAC."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core import signing
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import User
from apps.hardware_requests.kiosk_command_policy import OPERATIONS
from apps.hardware_requests.replay_failures import ReplayFailure
from apps.makerspaces import kiosk_station_services as kiosks
from apps.makerspaces.models_station_leases import StationOperatorLease, StationSessionRevocation
from apps.makerspaces.models_stations import StationCredential
from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.makerspaces.servability import is_servable
from apps.makerspaces.station_operator_leases import LEASE_HEADER, LEASE_SALT
from apps.makerspaces.station_sessions import read_session
from apps.makerspaces.station_views_public import assert_station_csrf


@dataclass(frozen=True)
class ReplayIdentity:
    station_id: int
    session_id: UUID
    version: int
    lease_id: UUID
    actor_id: int
    session_expires_at: datetime
    public_token: UUID

    def live(self, kind):
        credential_query = StationCredential.objects
        lease_query = StationOperatorLease.objects
        credential = credential_query.filter(station_id=self.station_id).first()
        if (credential is None or not credential.is_enabled or credential.version != self.version
                or credential.public_token != self.public_token):
            raise ReplayFailure("station_revoked")
        station = credential.station
        now = timezone.now()
        if self.session_expires_at <= now or StationSessionRevocation.objects.filter(
            session_id=self.session_id, station=station,
        ).exists():
            raise ReplayFailure("session_mismatch")
        lease = lease_query.filter(pk=self.lease_id).first()
        if lease is None or lease.revoked_at is not None or lease.expires_at <= now:
            raise ReplayFailure("lease_expired")
        if (lease.station_id != station.pk or lease.makerspace_id != station.makerspace_id
                or lease.actor_id != self.actor_id or lease.station_version != self.version
                or lease.station_session_id != self.session_id):
            raise ReplayFailure("session_mismatch")
        user = User.objects.filter(pk=self.actor_id, is_active=True).first()
        if (user is None or user.access_status != User.AccessStatus.ACTIVE
                or user.must_change_password or not is_servable(station.makerspace)):
            raise ReplayFailure("permission_revoked")
        operation = OPERATIONS[kind]
        if not all(module_enabled(station.makerspace, key) for key in operation.modules):
            raise ReplayFailure("module_disabled")
        if not all(feature_enabled(station.makerspace, key) for key in operation.features):
            raise ReplayFailure("feature_disabled")
        actions = set(lease.allowed_actions) & set(rbac.effective_actions(user, station.makerspace_id))
        if station.kind not in operation.station_kinds or not operation.actions <= actions:
            raise ReplayFailure("permission_revoked")
        return station, lease, user


def authenticate(request, station, public_token):
    # Origin validation must not depend on normal Django login/CSRF state.
    assert_station_csrf(request, station)
    try:
        session = read_session(request.COOKIES.get(kiosks.COOKIE_NAME, ""), salt=kiosks.COOKIE_SALT)
        lease = signing.loads(request.headers.get(LEASE_HEADER, ""), salt=LEASE_SALT)
        session_id = UUID(session["session_id"])
        expires = datetime.fromisoformat(session["expires_at"])
        if timezone.is_naive(expires):
            raise ValueError
        if (session["public_token"] != str(public_token)
                or lease["station_id"] != station.pk
                or lease["session_id"] != str(session_id)
                or lease["version"] != session["version"]):
            raise ValueError
        row = StationOperatorLease.objects.get(pk=UUID(lease["lease_id"]))
    except (KeyError, TypeError, ValueError, signing.BadSignature, StationOperatorLease.DoesNotExist):
        raise ReplayFailure("session_mismatch") from None
    return ReplayIdentity(station.pk, session_id, session["version"], row.pk, row.actor_id, expires, UUID(str(public_token)))
