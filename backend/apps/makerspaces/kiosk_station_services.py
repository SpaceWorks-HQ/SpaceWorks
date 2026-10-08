"""Kiosk (scanner/handover) Station lifecycle and the Station PIN session (phase 9b).

Built on the 9a shared core: ``station_credentials`` rotates/reveals/disables and
``station_sessions`` signs and resolves the cookie. Event Stations stay event-owned;
nothing here accepts the event kind. A Station is never an audit actor -- the admin
lifecycle records the staff User, PIN failure/session start record ``actor=None`` and
carry the Station identity in metadata.
"""

from datetime import timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit import services as audit
from apps.makerspaces.guards import require_feature, require_feature_locked
from apps.makerspaces.models_station_leases import (
    StationOperatorLease,
    StationSessionRevocation,
)
from apps.makerspaces.models_stations import Station, StationCredential
from apps.makerspaces.station_credentials import (
    disable as disable_credential,
    reveal as reveal_credential,
    rotate as rotate_credential,
)
from apps.makerspaces.station_security import peppered_material, pin_matches
from apps.makerspaces.station_sessions import resolve_session as resolve_shared, sign_session


KIOSK_FEATURE = "inventory.kiosk"
KIOSK_KINDS = (Station.Kind.SCANNER, Station.Kind.HANDOVER)
STATION_REFUSAL = "Invalid station request."
COOKIE_NAME = "sw_kiosk_station"
COOKIE_SALT = "spaceworks.kiosk.station-cookie.v1"


def cookie_path(public_token):
    return f"/api/v1/kiosk-stations/{public_token}/"


def _meta(station, credential, **extra):
    return {"station_id": station.pk, "station_version": credential.version, **extra}


def _pin_material(station_id, version, pin):
    return peppered_material(
        pepper=settings.EVENT_STATION_PIN_PEPPER,
        namespace="spaceworks:kiosk-station-pin:v1",
        identity=station_id,
        version=version,
        pin=pin,
    )


def _material_for(station):
    return lambda version, pin: _pin_material(station.pk, version, pin)


@transaction.atomic
def create_station(makerspace, *, actor, name, kind):
    if kind not in KIOSK_KINDS:
        raise ValidationError({"kind": "Only scanner and handover Stations are managed here."})
    locked = require_feature_locked(makerspace.pk, KIOSK_FEATURE)
    if Station.objects.filter(makerspace=locked, kind=kind, name=name).exists():
        raise ValidationError({"name": "A Station of this kind already has that name."})
    station = Station.objects.create(makerspace=locked, kind=kind, name=name, created_by=actor)
    credential, pin = rotate_credential(station, material_for=_material_for(station))
    audit.record(
        actor, "kiosk.station_created", makerspace=locked, target=station,
        meta=_meta(station, credential, station_kind=kind),
    )
    return station, credential, pin


def _locked_kiosk_station(station):
    require_feature_locked(station.makerspace_id, KIOSK_FEATURE)
    locked = Station.objects.select_for_update().get(pk=station.pk)
    if locked.kind not in KIOSK_KINDS:
        raise ValidationError({"station": "Not a kiosk Station."})
    return locked


@transaction.atomic
def rotate(station, *, actor):
    locked = _locked_kiosk_station(station)
    credential, pin = rotate_credential(locked, material_for=_material_for(locked))
    _revoke_station_leases(locked)
    audit.record(
        actor, "kiosk.station_pin_rotated", makerspace=locked.makerspace,
        target=locked, meta=_meta(locked, credential),
    )
    return credential, pin


@transaction.atomic
def reveal(station, *, actor, current_password):
    locked = _locked_kiosk_station(station)
    credential, pin = reveal_credential(locked, actor=actor, current_password=current_password)
    audit.record(
        actor, "kiosk.station_pin_revealed", makerspace=locked.makerspace,
        target=locked, meta=_meta(locked, credential),
    )
    return credential, pin


@transaction.atomic
def disable(station, *, actor):
    locked = Station.objects.select_for_update().get(pk=station.pk)
    if locked.kind not in KIOSK_KINDS:
        raise ValidationError({"station": "Not a kiosk Station."})
    credential = disable_credential(locked)
    _revoke_station_leases(locked)
    if credential is not None:
        audit.record(
            actor, "kiosk.station_disabled", makerspace=locked.makerspace,
            target=locked, meta=_meta(locked, credential),
        )
    return credential


def _revoke_station_leases(station, session_id=None):
    leases = StationOperatorLease.objects.filter(station=station, revoked_at__isnull=True)
    if session_id is not None:
        leases = leases.filter(station_session_id=session_id)
    return leases.update(revoked_at=timezone.now())


def observed_station(public_token):
    """Unauthenticated lookup used only to pick the origin set and tenant gate."""
    try:
        token = UUID(str(public_token))
    except (TypeError, ValueError, AttributeError):
        return None
    credential = StationCredential.objects.select_related("station__makerspace").filter(
        public_token=token, station__kind__in=KIOSK_KINDS,
    ).first()
    return credential.station if credential is not None else None


def start_session(public_token, *, pin):
    station = observed_station(public_token)
    if station is None:
        raise PermissionDenied(STATION_REFUSAL)
    failed = False
    with transaction.atomic():
        makerspace = require_feature_locked(station.makerspace_id, KIOSK_FEATURE)
        credential = StationCredential.objects.select_for_update().get(station=station)
        valid = credential.is_enabled and pin_matches(
            _pin_material(station.pk, credential.version, pin), credential.pin_digest,
        )
        if not valid:
            audit.record(
                None, "kiosk.station_pin_failed", makerspace=makerspace,
                target=station, meta=_meta(station, credential),
            )
            failed = True
        else:
            session_id = uuid4()
            expires_at = timezone.now() + timedelta(
                seconds=settings.KIOSK_STATION_SESSION_TTL_SECONDS
            )
            audit.record(
                None, "kiosk.station_session_started", makerspace=makerspace,
                target=station,
                meta=_meta(station, credential, station_session_id=str(session_id)),
            )
            cookie = sign_session(
                public_token=credential.public_token, version=credential.version,
                session_id=session_id, expires_at=expires_at, salt=COOKIE_SALT,
            )
    if failed:
        raise PermissionDenied(STATION_REFUSAL)
    return station, credential, session_id, cookie, expires_at


def resolve_session(public_token, cookie_value):
    """Live Station session: signature, version, enabled, kind, feature, revocation."""
    station, credential, session_id, expires_at = resolve_shared(
        public_token, cookie_value, salt=COOKIE_SALT, refusal=STATION_REFUSAL,
        with_expiry=True,
    )
    if station.kind not in KIOSK_KINDS:
        raise PermissionDenied(STATION_REFUSAL)
    if StationSessionRevocation.objects.filter(session_id=session_id).exists():
        raise PermissionDenied(STATION_REFUSAL)
    require_feature(station.makerspace, KIOSK_FEATURE)
    return station, credential, session_id, expires_at


@transaction.atomic
def end_session(station, *, session_id, expires_at):
    StationSessionRevocation.objects.get_or_create(
        session_id=session_id, defaults={"station": station, "expires_at": expires_at},
    )
    return _revoke_station_leases(station, session_id=session_id)
