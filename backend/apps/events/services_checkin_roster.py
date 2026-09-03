from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.events.checkin_policy import download_is_open
from apps.events.checkin_roster import minimum_roster
from apps.events.checkin_tokens import build_lease
from apps.events.models import Event, EventCheckInStationCredential
from apps.makerspaces.guards import require_feature_locked


class RosterWindowClosed(APIException):
    status_code = 409
    default_detail = "The offline roster is unavailable outside the event check-in window."
    default_code = "outside_window"


@transaction.atomic
def issue_roster(
    event,
    *,
    actor,
    kind,
    session_id=None,
    station_version=None,
):
    from apps.events import services

    locked = services._locked_event(event.pk)
    locked.makerspace = require_feature_locked(
        locked.makerspace_id, "events.offline_checkin"
    )
    if locked.status not in (Event.Status.PUBLISHED, Event.Status.COMPLETED):
        raise RosterWindowClosed()
    if not download_is_open(locked):
        raise RosterWindowClosed()
    if kind == "station":
        credential = EventCheckInStationCredential.objects.select_for_update().filter(
            event=locked,
            is_enabled=True,
            version=station_version,
        ).first()
        if credential is None:
            raise RosterWindowClosed()

    lease, lease_token = build_lease(
        locked,
        kind=kind,
        actor_id=actor.pk if actor is not None else None,
        session_id=session_id,
        station_version=station_version,
    )
    rows = minimum_roster(locked)
    services._audit(
        locked,
        actor,
        "event.checkin_roster_downloaded",
        locked,
        {
            "lease_id": lease["lease_id"],
            "station_version": station_version,
            "registration_count": len(rows),
            "expires_at": lease["expires_at"],
        },
    )
    return {
        "lease_token": lease_token,
        "lease_id": lease["lease_id"],
        "server_time": timezone.now(),
        "issued_at": lease["issued_at"],
        "expires_at": lease["expires_at"],
        "scan_opens_at": lease["scan_opens_at"],
        "scan_closes_at": lease["scan_closes_at"],
        "sync_deadline": lease["sync_deadline"],
        "event": {
            "id": locked.pk,
            "title": locked.title,
            "starts_at": locked.starts_at,
            "ends_at": locked.ends_at,
        },
        "registrations": rows,
    }
