import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.integrations import notify, webhooks
from apps.integrations.destinations import NotificationScope
from apps.integrations.dispatch_channels import _deliver_notification
from apps.integrations.models import NotificationDeliveryLog, NotificationDestination
from apps.integrations.notification_catalog import FEATURE_EVENTS
from apps.integrations.notify import LifecyclePayload
from tests.return_helpers import make_space


@pytest.mark.parametrize("feature,event", [
    (feature, event) for feature, events in FEATURE_EVENTS.items() for event in events
] + [("reports", "scheduled_report")])
def test_every_catalog_event_has_a_versioned_unambiguous_name(feature, event):
    occurred_at = "2026-10-10T01:02:03+00:00"
    payload = {"request_id": 12, "scope": {"machine_id": 9}, "occurred_at": occurred_at}
    log = SimpleNamespace(
        pk=1, event=event, feature=feature, makerspace_id=7, text_body="Staff update",
        payload=payload, created_at=timezone.now(),
    )
    body = webhooks.webhook_event_body(log)
    assert body["event"] == event  # Compatibility: the old bare key is unchanged.
    assert body["feature"] == feature
    assert body["text"] == "Staff update"
    assert body["data"] == payload
    assert body["structured"] == {
        "version": 1, "event": f"{feature}.{event}", "ids": {"request_id": 12},
        "makerspace": {"id": 7}, "occurred_at": occurred_at,
    }


def test_legacy_queued_row_uses_delivery_creation_time_without_inventing_ids():
    created_at = timezone.now()
    log = SimpleNamespace(
        pk=1, event="accepted", feature="hardware_requests", makerspace_id=7,
        text_body="Update", payload={"scope": {"machine_id": 9}}, created_at=created_at,
    )
    body = webhooks.webhook_event_body(log)
    assert body["structured"]["ids"] == {}
    assert body["structured"]["occurred_at"] == created_at.isoformat()


@pytest.mark.django_db
def test_payload_ids_scope_and_event_time_survive_fanout_queue_delay_and_retry(
    monkeypatch, django_capture_on_commit_callbacks,
):
    space = make_space("structured-webhook")
    destinations = []
    for label in ("ERP", "Automation"):
        dest = NotificationDestination(makerspace=space, channel="webhook", label=label)
        dest.set_webhook_url("https://hooks.example.test/events")
        dest.set_signing_secret("private-signing-secret")
        dest.save()
        destinations.append(dest)
    monkeypatch.setattr(notify, "is_notification_enabled", lambda space, feature, channel: channel == "webhook")
    monkeypatch.setattr("apps.integrations.dispatch_channels._enqueue_notification", Mock())
    clock = Mock(return_value=timezone.now())
    event_time = clock.return_value.isoformat()
    monkeypatch.setattr(notify.timezone, "now", clock)
    with django_capture_on_commit_callbacks(execute=True):
        result = notify.notify_lifecycle(
            space, feature="hardware_requests", event="accepted",
            build=lambda: LifecyclePayload(
                text="Hardware accepted",
                data={"request_id": 12, "email": "private@example.test", "secret": "private"},
                scope=NotificationScope(category=9),
            ),
        )
        # The queue may build the payload later; occurred_at must remain the event time.
        clock.return_value += timedelta(hours=1)
    assert result.scheduled
    logs = list(NotificationDeliveryLog.objects.order_by("pk"))
    assert len(logs) == len(destinations)
    assert all(log.payload == {
        "request_id": 12, "occurred_at": event_time,
        "scope": NotificationScope(category=9).as_dict(),
    } for log in logs)
    sent = []

    def deliver(url, body, headers):
        sent.append((body, headers))
        if len(sent) == 1:
            raise webhooks.WebhookDeliveryError("temporary failure")

    monkeypatch.setattr(webhooks, "_deliver", deliver)
    log = logs[0]
    _deliver_notification(log)
    assert log.status == "failed"
    _deliver_notification(log)
    assert log.status == "sent"
    assert sent[0][0] == sent[1][0]
    body = json.loads(sent[1][0])
    assert body["structured"]["ids"] == {"request_id": 12}
    assert body["structured"]["occurred_at"] == event_time
    assert sent[1][1][webhooks.EVENT_HEADER] == "accepted"
    assert "private" not in sent[1][0].decode()
