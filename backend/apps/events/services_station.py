from datetime import datetime
import hashlib
import hmac
import secrets
from urllib.parse import quote
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

# EVERY public station refusal uses this one string. Distinguishing "bad credential"
# from "bad request" tells an attacker which check they passed, which turns the
# station into an oracle for whether a PIN, session or event window is valid.
STATION_REFUSAL = "Invalid station request."

from apps.accounts.models import User
from apps.apiclients.crypto import decrypt_secret, encrypt_secret
from apps.events.checkin_policy import window_for
from apps.events.checkin_tokens import read_station_cookie, sign_station_cookie
from apps.events.models import Event, EventCheckInStationCredential
from apps.makerspaces.guards import require_feature, require_feature_locked


STATION_COOKIE_NAME = "sw_event_station"


class StationSecretUnavailable(APIException):
    status_code = 503
    default_detail = "Station credential encryption is not configured."
    default_code = "station_secret_unavailable"


class PasswordStepUpUnavailable(APIException):
    status_code = 409
    default_detail = "This account cannot use password reveal; rotate the PIN instead."
    default_code = "password_step_up_unavailable"


def station_url(event, public_token):
    if event.makerspace.frontend_domain and event.makerspace.frontend_domain_status == "verified":
        return f"https://{event.makerspace.frontend_domain}/event-check-in/{quote(str(public_token))}"
    base = (settings.PUBLIC_APP_BASE_URL or "http://localhost:5000").rstrip("/")
    return f"{base}/m/{quote(event.makerspace.slug)}/event-check-in/{quote(str(public_token))}"


def status_payload(event, credential=None):
    if credential is None:
        credential = EventCheckInStationCredential.objects.filter(event=event).first()
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
    credential = EventCheckInStationCredential.objects.select_for_update().filter(
        event=locked
    ).first()
    version = credential.version + 1 if credential else 1
    pin = f"{secrets.randbelow(100_000_000):08d}"
    while credential is not None and check_password(
        _pin_material(locked.pk, credential.version, pin),
        credential.pin_digest,
    ):
        pin = f"{secrets.randbelow(100_000_000):08d}"
    digest = make_password(_pin_material(locked.pk, version, pin))
    try:
        ciphertext = encrypt_secret(pin)
    except (ImproperlyConfigured, ValueError, TypeError) as exc:
        raise StationSecretUnavailable() from exc
    now = timezone.now()
    if credential is None:
        credential = EventCheckInStationCredential.objects.create(
            event=locked,
            pin_digest=digest,
            pin_ciphertext=ciphertext,
            version=version,
            is_enabled=True,
            rotated_at=now,
        )
    else:
        credential.pin_digest = digest
        credential.pin_ciphertext = ciphertext
        credential.version = version
        credential.is_enabled = True
        credential.rotated_at = now
        credential.disabled_at = None
        credential.save(
            update_fields=[
                "pin_digest", "pin_ciphertext", "version", "is_enabled",
                "rotated_at", "disabled_at", "updated_at",
            ]
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
    credential = EventCheckInStationCredential.objects.select_for_update().filter(
        event=locked,
        is_enabled=True,
    ).first()
    if credential is None:
        raise PasswordStepUpUnavailable("Rotate a station PIN before revealing it.")
    principal = User.objects.select_for_update().get(pk=actor.pk)
    if not principal.has_usable_password():
        raise PasswordStepUpUnavailable()
    if not principal.check_password(current_password):
        raise PermissionDenied("Current password is incorrect.")
    try:
        pin = decrypt_secret(credential.pin_ciphertext)
    except (ImproperlyConfigured, ValueError, TypeError) as exc:
        raise StationSecretUnavailable() from exc
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
    credential = EventCheckInStationCredential.objects.select_for_update().filter(
        event=locked
    ).first()
    if credential is None:
        return None
    credential.is_enabled = False
    credential.disabled_at = timezone.now()
    credential.save(update_fields=["is_enabled", "disabled_at", "updated_at"])
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
    observed = EventCheckInStationCredential.objects.filter(
        public_token=token
    ).values_list("event_id", flat=True).first()
    if observed is None:
        raise PermissionDenied(STATION_REFUSAL)
    failed = False
    with transaction.atomic():
        event = services._locked_event(observed)
        event.makerspace = require_feature_locked(
            event.makerspace_id, "events.offline_checkin"
        )
        credential = EventCheckInStationCredential.objects.select_for_update().filter(
            event=event,
            public_token=token,
        ).first()
        now = timezone.now()
        window = window_for(event)
        valid = (
            credential is not None
            and credential.is_enabled
            and event.status in (Event.Status.PUBLISHED, Event.Status.COMPLETED)
            and window.opens_at <= now <= window.closes_at
            and check_password(
                _pin_material(event.pk, credential.version, pin),
                credential.pin_digest,
            )
        )
        if not valid:
            if credential is not None:
                services._audit(
                    event,
                    None,
                    "event.station_pin_failed",
                    event,
                    {"event_id": event.pk, "station_version": credential.version},
                )
            failed = True
        else:
            session_id = uuid4()
            services._audit(
                event,
                None,
                "event.station_session_started",
                event,
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
    # Raise only after the atomic block commits so bounded failed-PIN audit entries survive.
    if failed:
        raise PermissionDenied(STATION_REFUSAL)
    return event, credential, session_id, cookie, window.sync_deadline


def resolve_session(public_token, cookie_value):
    try:
        token = UUID(str(public_token))
        payload = read_station_cookie(cookie_value)
        session_id = UUID(payload["session_id"])
        expires_at = datetime.fromisoformat(payload["expires_at"])
    except Exception:
        raise PermissionDenied("Invalid station session.") from None
    credential = EventCheckInStationCredential.objects.select_related(
        "event__makerspace"
    ).filter(
        public_token=token,
        is_enabled=True,
        version=payload.get("version"),
    ).first()
    if (
        credential is None
        or payload.get("public_token") != str(token)
        or timezone.now() > expires_at
    ):
        raise PermissionDenied("Invalid station session.")
    require_feature(credential.event.makerspace, "events.offline_checkin")
    return credential.event, credential, session_id


def _pin_material(event_id, version, pin):
    pepper = str(settings.EVENT_STATION_PIN_PEPPER or "").encode("utf-8")
    if len(pepper) < 32:
        raise StationSecretUnavailable()
    message = f"spaceworks:event-station-pin:v1:{event_id}:{version}:{pin}".encode()
    return hmac.new(pepper, message, hashlib.sha256).hexdigest()
