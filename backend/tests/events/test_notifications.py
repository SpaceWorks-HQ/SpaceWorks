import pytest
from django.test import override_settings

from apps.events import notifications, services
from apps.events.models import Event, EventRegistration
from apps.integrations.models import NotificationPreference
from apps.integrations.notification_catalog import FEATURE_EVENTS
from tests.events.test_services import (
    make_actor,
    make_event,
    make_registration,
    make_space,
)

pytestmark = pytest.mark.django_db


def test_each_event_service_lifecycle_reaches_fanout_once(monkeypatch):
    calls = []
    monkeypatch.setattr(
        services,
        "notify_event_lifecycle",
        lambda event, name, registration_id=None: calls.append(
            (name, registration_id)
        ),
    )
    space, actor = make_space("event-fanout"), make_actor("event-fanout-actor")

    draft = make_event(space, title="Draft", status=Event.Status.DRAFT)
    services.publish(draft, actor=actor)
    services.cancel(make_event(space, title="Cancel"), actor=actor)
    services.complete(make_event(space, title="Complete"), actor=actor)
    services.register(
        make_event(space, title="Register"),
        name="Guest",
        email="created@example.com",
        phone="1",
    )

    promotion_event = make_event(space, title="Promotion", capacity=1)
    registered = make_registration(
        promotion_event, "registered@example.com",
        EventRegistration.Status.REGISTERED,
    )
    waiter = make_registration(
        promotion_event, "waiter@example.com",
        EventRegistration.Status.WAITLISTED,
    )
    services.cancel_registration(registered)
    attended = make_registration(
        make_event(space, title="Attend"), "attend@example.com"
    )
    services.mark_attended(attended, actor=actor)

    assert [name for name, _ in calls] == [
        "published",
        "cancelled",
        "completed",
        "registration_created",
        "registration_cancelled",
        "registration_promoted",
        "registration_attended",
    ]
    assert calls[5][1] == waiter.pk


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_event_notifications_are_silent_until_email_cell_enabled(monkeypatch):
    event = make_event(make_space("event-pref"))
    monkeypatch.setattr(
        notifications,
        "staff_emails_for_feature",
        lambda *args, **kwargs: ["events@example.com"],
    )
    silent = notifications.notify_event_lifecycle(event, "published", sync=True)
    assert silent.delivered_counts == {}

    NotificationPreference.objects.create(
        makerspace=event.makerspace,
        feature="events",
        channel="email",
        enabled=True,
    )
    delivered = notifications.notify_event_lifecycle(event, "published", sync=True)
    assert delivered.delivered_counts == {"email": 1}


def test_approval_lifecycle_uses_catalogued_notification_events(monkeypatch):
    calls = []
    monkeypatch.setattr(
        services,
        "notify_event_lifecycle",
        lambda event, name, registration_id=None: calls.append(name),
    )
    event = make_event(
        make_space("event-approval-fanout"),
        capacity=1,
        registration_requires_approval=True,
    )
    first = services.register(
        event, name="First", email="approval-first@example.test", phone="1"
    )
    second = services.register(
        event, name="Second", email="approval-second@example.test", phone="1"
    )
    services.approve_registration(first, actor=None)
    second = services.approve_registration(second, actor=None)
    services.reject_registration(second, actor=None)

    assert calls == [
        "registration_pending_approval",
        "registration_pending_approval",
        "registration_approved",
        "registration_approved",
        "registration_rejected",
    ]
    assert set(calls) <= set(FEATURE_EVENTS["events"])
