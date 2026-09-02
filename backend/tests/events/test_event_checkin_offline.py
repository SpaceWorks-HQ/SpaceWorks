from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.events import services
from apps.events.models import EventCheckInEvent
from tests.events.checkin_helpers import (
    client_for,
    make_event,
    make_member,
    make_space,
    make_staff,
    register,
)

pytestmark = pytest.mark.django_db


def enable_offline(space):
    space.enabled_features = [*space.enabled_features, "events.offline_checkin"]
    space.save(update_fields=["enabled_features"])


def roster_url(event):
    return reverse("admin-event-check-in-offline-roster", kwargs={"pk": event.pk})


def sync_url(event):
    return reverse("admin-event-check-in-offline-sync", kwargs={"pk": event.pk})


def test_feature_defaults_off_but_online_confirmation_still_works():
    space = make_space()
    event = make_event(space)
    registration = register(event, make_member(space))
    client = client_for(make_staff(space))

    assert client.get(roster_url(event)).status_code == 400
    confirmed = client.post(
        reverse(
            "admin-event-registration-mark-attended",
            kwargs={"pk": registration.pk},
        ),
        {},
        format="json",
    )

    assert confirmed.status_code == 200
    history = EventCheckInEvent.objects.get(registration=registration)
    assert history.source == EventCheckInEvent.Source.ONLINE


def test_enabled_roster_is_minimal_expiring_and_not_cacheable():
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)
    registration.custom_answers = {"diet": "private"}
    registration.save(update_fields=["custom_answers"])

    response = client_for(make_staff(space)).get(roster_url(event))

    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert set(response.data) == {
        "lease_token", "lease_id", "server_time", "issued_at", "expires_at",
        "scan_opens_at", "scan_closes_at", "sync_deadline", "event",
        "registrations",
    }
    assert set(response.data["event"]) == {"id", "title", "starts_at", "ends_at"}
    assert response.data["registrations"] == [
        {
            "registration_id": registration.pk,
            "checkin_token": str(registration.checkin_token),
            "name": member.display_name,
            "host_waiver_state": "not_required",
        }
    ]
    rendered = str(response.data)
    assert member.email not in rendered
    assert member.phone not in rendered
    assert "private" not in rendered
    assert response.data["expires_at"] <= response.data["sync_deadline"]


def test_sync_records_reported_and_server_times_without_attendee_pii_in_audit():
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)
    staff = make_staff(space)
    client = client_for(staff)
    roster = client.get(roster_url(event)).data
    operation_id = uuid4()
    occurred_at = timezone.now() - timedelta(minutes=8)

    response = client.post(
        sync_url(event),
        {
            "lease_token": roster["lease_token"],
            "operations": [{
                "operation_id": str(operation_id),
                "checkin_token": str(registration.checkin_token),
                "reported_occurred_at": occurred_at.isoformat(),
            }],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["results"][0]["outcome"] == "applied"
    history = EventCheckInEvent.objects.get(operation_id=operation_id)
    assert history.source == EventCheckInEvent.Source.OFFLINE_SYNC
    assert history.actor == staff
    assert history.attended_at == occurred_at
    assert history.recorded_at > history.attended_at
    audit = AuditLog.objects.get(
        action="event.registration_attended", target_id=str(registration.pk)
    )
    assert audit.meta["reported_occurred_at"] == occurred_at.isoformat()
    assert audit.meta["recorded_at"] == history.recorded_at.isoformat()
    assert member.email not in str(audit.meta)
    assert member.phone not in str(audit.meta)


def test_sync_is_idempotent_and_rejects_stale_registration_and_event_state():
    space = make_space()
    enable_offline(space)
    staff = make_staff(space)
    client = client_for(staff)
    cancelled_event = make_event(space, title="Cancelled event")
    cancelled_event_row = register(
        cancelled_event, make_member(space, "cancelled-event-member")
    )
    cancelled_event_roster = client.get(roster_url(cancelled_event)).data
    services.cancel(cancelled_event, actor=staff)

    def operation(row, value):
        return {
            "operation_id": str(value),
            "checkin_token": str(row.checkin_token),
            "reported_occurred_at": timezone.now().isoformat(),
        }

    cancelled_response = client.post(
        sync_url(cancelled_event),
        {
            "lease_token": cancelled_event_roster["lease_token"],
            "operations": [operation(cancelled_event_row, uuid4())],
        },
        format="json",
    )
    assert cancelled_response.data["results"][0]["outcome"] == "event_unavailable"

    event = make_event(space, title="Active event")
    rows = [register(event, make_member(space, f"member-{i}")) for i in range(2)]
    roster = client.get(roster_url(event)).data
    operation_id = uuid4()
    services.cancel_registration(rows[1], actor=staff)
    stale = client.post(
        sync_url(event),
        {"lease_token": roster["lease_token"], "operations": [operation(rows[1], uuid4())]},
        format="json",
    )
    assert stale.data["results"][0]["outcome"] == "registration_changed"

    payload = {"lease_token": roster["lease_token"], "operations": [operation(rows[0], operation_id)]}
    first = client.post(sync_url(event), payload, format="json")
    second = client.post(sync_url(event), payload, format="json")
    assert first.data["results"][0]["outcome"] == "applied"
    assert second.data["results"][0]["outcome"] == "duplicate_operation"
    assert EventCheckInEvent.objects.filter(operation_id=operation_id).count() == 1


def test_staff_from_another_makerspace_cannot_download_the_roster():
    host, other = make_space("offline-host"), make_space("offline-other")
    enable_offline(host)
    event = make_event(host)

    response = client_for(make_staff(other)).get(roster_url(event))

    assert response.status_code in (403, 404)
