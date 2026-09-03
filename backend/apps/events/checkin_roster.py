from django.conf import settings
from rest_framework.exceptions import APIException

from apps.events.models import EventRegistration
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver
from apps.makerspaces.waiver_state import acceptance_on_file_q


class RosterTooLarge(APIException):
    status_code = 413
    default_detail = "This roster is too large for offline storage."
    default_code = "roster_too_large"


def host_waiver_state(registration):
    if not MakerspaceWaiver.objects.filter(
        makerspace_id=registration.event.makerspace_id,
        is_active=True,
    ).exists():
        return "not_required"
    if registration.host_waiver_id:
        return "on_file"
    if registration.member_id and MakerspaceMembership.objects.filter(
        user_id=registration.member_id,
        makerspace_id=registration.event.makerspace_id,
    ).filter(acceptance_on_file_q()).exists():
        return "on_file"
    return "missing"


def minimum_roster(event):
    rows = list(
        EventRegistration.objects.filter(
            event=event,
            status=EventRegistration.Status.REGISTERED,
        )
        .select_related("event")
        .order_by("created_at", "id")[: settings.EVENT_CHECKIN_ROSTER_MAX + 1]
    )
    if len(rows) > settings.EVENT_CHECKIN_ROSTER_MAX:
        raise RosterTooLarge()
    return [
        {
            "registration_id": row.pk,
            "checkin_token": row.checkin_token,
            "name": row.name,
            "host_waiver_state": host_waiver_state(row),
        }
        for row in rows
    ]
