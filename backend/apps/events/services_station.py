from urllib.parse import quote
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.events.checkin_policy import window_for
from apps.events.checkin_tokens import STATION_COOKIE_SALT, sign_station_cookie
from apps.events.models import Event, EventStationBinding
from apps.makerspaces.guards import require_feature, require_feature_locked
from apps.makerspaces.models import Station, StationCredential
from apps.makerspaces.station_credentials import (
    PasswordStepUpUnavailable,
    disable as disable_credential,
    reveal as reveal_credential,
    rotate as rotate_credential,
)
from apps.makerspaces.station_security import (
    StationSecretUnavailable,
    peppered_material,
    pin_matches,
)
from apps.makerspaces.station_sessions import resolve_session as resolve_shared_session


STATION_REFUSAL = "Invalid station request."
STATION_COOKIE_NAME = "sw_event_station"


def station_url(event, public_token):
    if event.makerspace.frontend_domain and event.makerspace.frontend_domain_status == "verified":
        return f"https://{event.makerspace.frontend_domain}/event-check-in/{quote(str(public_token))}"
    base = (settings.PUBLIC_APP_BASE_URL or "http://localhost:5000").rstrip("/")
    return f"{base}/m/{quote(event.makerspace.slug)}/event-check-in/{quote(str(public_token))}"


def binding_for_event(event, *, lock=False, create=False, actor=None):
    queryset = EventStationBinding.objects.select_related("station")
    if lock:
        queryset = queryset.select_for_update()
    binding = queryset.filter(event=event).first()
    if binding is not None:
        _validate_event_binding(binding)
        return binding
    if not create:
        return None
    station = Station.objects.create(
        makerspace=event.makerspace,
        kind=Station.Kind.EVENT_CHECKIN,
        name=f"event-{event.pk}",
        created_by=actor,
    )
    return EventStationBinding.objects.create(event=event, station=station)


def credential_for_event(event, *, lock=False, enabled=None):
    binding = binding_for_event(event, lock=lock)
    if binding is None:
        return None
    queryset = StationCredential.objects.filter(station=binding.station)
    if lock:
        queryset = queryset.select_for_update()
    if enabled is not None:
        queryset = queryset.filter(is_enabled=enabled)
    return queryset.first()


def status_payload(event, credential=None):
    credential = credential if credential is not None else credential_for_event(event)
    if credential is None:
        return {"configured": False}
    return {
        "configured": True,
        "enabled": credential.is_enabled,
        "public_token": credential.public_token,
        "version": credential.version,
        "station_url": station_url(event, credential.public_token),
        "rotated_at": credential.rotated_at,
    }


@transaction.atomic
def rotate(event, *, actor):
    from apps.events import services

    locked = services._locked_event(event.pk)
    locked.makerspace = require_feature_locked(
        locked.makerspace_id, "events.offline_checkin"
    )
    binding = binding_for_event(locked, lock=True, create=True, actor=actor)
    credential, pin = rotate_credential(
        binding.station,
        material_for=lambda version, value: _pin_material(locked.pk, version, value),
    )
    services._audit(
        locked,
        actor,
        "event.station_pin_rotated",
        locked,
        {"event_id": locked.pk, "station_version": credential.version},
    )
    return credential, pin


@transaction.atomic
def reveal(event, *, actor, current_password):
    from apps.events import services

    locked = services._locked_event(event.pk)
    locked.makerspace = require_feature_locked(
        locked.makerspace_id, "events.offline_checkin"
    )
    binding = binding_for_event(locked, lock=True)
    if binding is None:
        raise PasswordStepUpUnavailable("Rotate a station PIN before revealing it.")
    credential, pin = reveal_credential(
        binding.station,
        actor=actor,
        current_password=current_password,
    )
    services._audit(
        locked,
        actor,
        "event.station_pin_revealed",
        locked,
        {"event_id": locked.pk, "station_version": credential.version},
    )
    return credential, pin


@transaction.atomic
def disable(event, *, actor):
    from apps.events import services

    locked = services._locked_event(event.pk)
    locked.makerspace = require_feature_locked(
        locked.makerspace_id, "events.offline_checkin"
    )
    binding = binding_for_event(locked, lock=True)
    credential = disable_credential(binding.station) if binding else None
    if credential is None:
        return None
    services._audit(
        locked,
        actor,
        "event.station_disabled",
        locked,
        {"event_id": locked.pk, "station_version": credential.version},
    )
    return credential


def start_session(public_token, *, pin):
    from apps.events import services

    try:
        token = UUID(str(public_token))
    except (TypeError, ValueError, AttributeError):
        raise PermissionDenied(STATION_REFUSAL) from None
    observed = StationCredential.objects.filter(
        public_token=token,
        station__event_binding__isnull=False,
    ).values_list("station__event_binding__event_id", flat=True).first()
    if observed is None:
        raise PermissionDenied(STATION_REFUSAL)
    failed = False
    with transaction.atomic():
        event = services._locked_event(observed)
        event.makerspace = require_feature_locked(
            event.makerspace_id, "events.offline_checkin"
        )
        binding = binding_for_event(event, lock=True)
        credential = (
            StationCredential.objects.select_for_update()
            .filter(station=binding.station)
            .first()
            if binding is not None
            else None
        )
        now = timezone.now()
        window = window_for(event)
        valid = (
            credential is not None
            and credential.public_token == token
            and credential.is_enabled
            and event.status in (Event.Status.PUBLISHED, Event.Status.COMPLETED)
            and window.opens_at <= now <= window.closes_at
            and pin_matches(
                _pin_material(event.pk, credential.version, pin),
                credential.pin_digest,
            )
        )
        if not valid:
            if credential is not None:
                services._audit(
                    event, None, "event.station_pin_failed", event,
                    {"event_id": event.pk, "station_version": credential.version},
                )
            failed = True
        else:
            session_id = uuid4()
            services._audit(
                event, None, "event.station_session_started", event,
                {
                    "event_id": event.pk,
                    "session_id": str(session_id),
                    "station_version": credential.version,
                },
            )
            cookie = sign_station_cookie(
                public_token=credential.public_token,
                version=credential.version,
                session_id=session_id,
                expires_at=window.sync_deadline,
            )
    if failed:
        raise PermissionDenied(STATION_REFUSAL)
    return event, credential, session_id, cookie, window.sync_deadline


def resolve_session(public_token, cookie_value):
    station, credential, session_id = resolve_shared_session(
        public_token,
        cookie_value,
        salt=STATION_COOKIE_SALT,
        refusal="Invalid station session.",
    )
    binding = EventStationBinding.objects.select_related("event__makerspace").filter(
        station=station
    ).first()
    if binding is None:
        raise PermissionDenied("Invalid station session.")
    try:
        _validate_event_binding(binding)
    except ValidationError:
        raise PermissionDenied("Invalid station session.") from None
    require_feature(binding.event.makerspace, "events.offline_checkin")
    return binding.event, credential, session_id


def _validate_event_binding(binding):
    if binding.event.makerspace_id != binding.station.makerspace_id:
        raise ValidationError("Event and Station must belong to the same makerspace.")
    if binding.station.kind != Station.Kind.EVENT_CHECKIN:
        raise ValidationError("Event bindings require an event check-in Station.")


def _pin_material(event_id, version, pin):
    return peppered_material(
        pepper=settings.EVENT_STATION_PIN_PEPPER,
        namespace="spaceworks:event-station-pin:v1",
        identity=event_id,
        version=version,
        pin=pin,
    )
