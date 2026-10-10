import pytest

from apps.audit.models import AuditLog
from apps.integrations.models import EmailLog, NotificationDeliveryLog, NotificationDestination
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def failed(space):
    return NotificationDeliveryLog.objects.create(makerspace=space, channel="slack", feature="bookings",
        event="confirmed", text_body="Staff text", status="failed", error="notification_delivery_failed:TimeoutError")


def base(space):
    return f"/api/v1/integrations/makerspace/{space.pk}"


def test_delivery_list_unifies_channels_filters_and_is_tenant_scoped():
    space, other = make_space("f2-log-list"), make_space("f2-log-other")
    actor = make_member("f2-log-manager", space)
    channel = failed(space)
    failed(other)
    email = EmailLog.objects.create(makerspace=space, to_email="member@example.test", subject="Own message",
                                  stream="bookings", feature="bookings", event="confirmed", status="sent")
    client = authenticated_client(actor)
    response = client.get(f"{base(space)}/delivery-logs")
    assert response.status_code == 200
    assert response.data["count"] == 2
    assert {(row["kind"], row["id"]) for row in response.data["results"]} == {("channel", channel.pk), ("email", email.pk)}
    assert "Own message" not in str(response.data)
    assert client.get(f"{base(space)}/delivery-logs?channel=slack&status=failed&event=confirmed").data["count"] == 1
    assert client.get(f"{base(space)}/delivery-logs?status=unknown").status_code == 400
    assert client.get(f"{base(other)}/delivery-logs").status_code == 404


def test_retry_generation_prevents_repeated_clicks_even_if_enqueue_fails_again(monkeypatch, django_capture_on_commit_callbacks):
    space = make_space("f2-retry-once")
    actor = make_member("f2-retry-manager", space)
    log = failed(space)
    calls = []
    def enqueue(pk):
        calls.append(pk)
        NotificationDeliveryLog.objects.filter(pk=pk).update(status="failed")
    monkeypatch.setattr("apps.integrations.dispatch_channels._enqueue_notification", enqueue)
    path = f"{base(space)}/delivery-logs/channel/{log.pk}/retry"
    client = authenticated_client(actor)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(path, {"generation": 0}, format="json").status_code == 200
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(path, {"generation": 0}, format="json").status_code == 200
    assert calls == [log.pk]
    assert AuditLog.objects.filter(actor=actor, action="notification.delivery_requeued").count() == 1
    log.refresh_from_db()
    assert log.retry_generation == 1
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(path, {"generation": 1}, format="json").status_code == 200
    assert calls == [log.pk, log.pk]


def test_retry_refuses_skips_and_cannot_reach_foreign_logs(monkeypatch):
    space, other = make_space("f2-retry-scope"), make_space("f2-retry-foreign")
    actor = make_member("f2-retry-scope-manager", space)
    skipped = failed(space)
    skipped.status = "skipped"
    skipped.save(update_fields=["status"])
    foreign = failed(other)
    client = authenticated_client(actor)
    assert client.post(f"{base(space)}/delivery-logs/channel/{skipped.pk}/retry", {"generation": 0}, format="json").status_code == 400
    assert client.post(f"{base(space)}/delivery-logs/channel/{foreign.pk}/retry", {"generation": 0}, format="json").status_code == 404
    assert not AuditLog.objects.filter(action="notification.delivery_requeued").exists()


def test_send_test_only_addresses_actor_or_an_explicit_scoped_destination(monkeypatch, django_capture_on_commit_callbacks):
    space, other = make_space("f2-test-send"), make_space("f2-test-other")
    actor = make_member("f2-test-manager", space)
    monkeypatch.setattr("apps.integrations.dispatch_outbox._enqueue", lambda pk: None)
    client = authenticated_client(actor)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"{base(space)}/delivery-test", {"to_email": "someone-else@example.test"}, format="json")
    assert response.status_code == 200
    log = EmailLog.objects.get(pk=response.data["id"])
    assert log.to_email == actor.email and log.recipient_id == actor.pk
    assert AuditLog.objects.filter(actor=actor, action="notification.test_sent").exists()
    destination = NotificationDestination.objects.create(makerspace=other, channel="telegram",
                                                         label="Foreign room", telegram_chat_id="123")
    assert client.post(f"{base(space)}/delivery-test", {"destination_id": destination.pk}, format="json").status_code == 404
    space.enabled_modules = [key for key in space.enabled_modules if key != "email"]
    space.save(update_fields=["enabled_modules"])
    assert client.post(f"{base(space)}/delivery-test", {}, format="json").status_code == 400


def test_email_retry_uses_same_generation_and_delivery_rechecks_suppression(monkeypatch, django_capture_on_commit_callbacks):
    space = make_space("f2-email-retry")
    actor = make_member("f2-email-retry-manager", space)
    log = EmailLog.objects.create(makerspace=space, to_email=actor.email, subject="Message", text_body="Own body", status="failed")
    calls = []
    monkeypatch.setattr("apps.integrations.dispatch._enqueue", calls.append)
    client = authenticated_client(actor)
    path = f"{base(space)}/delivery-logs/email/{log.pk}/retry"
    with django_capture_on_commit_callbacks(execute=True):
        first = client.post(path, {"generation": 0}, format="json")
        second = client.post(path, {"generation": 0}, format="json")
    assert first.status_code == second.status_code == 200
    assert calls == [log.pk]
    assert AuditLog.objects.filter(actor=actor, action="email.retried").count() == 1


def test_retry_channel_off_returns_400_without_enqueue_or_audit(monkeypatch):
    space = make_space("f2-retry-module-off")
    actor = make_member("f2-retry-off-manager", space)
    log = failed(space)
    space.enabled_modules = [key for key in space.enabled_modules if key != "slack"]
    space.save(update_fields=["enabled_modules"])
    calls = []
    monkeypatch.setattr("apps.integrations.dispatch_channels._enqueue_notification", calls.append)
    response = authenticated_client(actor).post(f"{base(space)}/delivery-logs/channel/{log.pk}/retry",
                                                {"generation": 0}, format="json")
    assert response.status_code == 400
    log.refresh_from_db()
    assert log.status == "failed" and log.retry_generation == 0 and not calls
    assert not AuditLog.objects.filter(action="notification.delivery_requeued").exists()


def test_retry_of_a_row_already_removed_by_retention_is_a_typed_not_found():
    from rest_framework.exceptions import NotFound
    from apps.integrations.delivery_services import retry_delivery
    space = make_space("f2-retry-retained-away")
    actor = make_member("f2-retry-retained-manager", space)
    log = failed(space)
    NotificationDeliveryLog.objects.filter(pk=log.pk).delete()
    with pytest.raises(NotFound):
        retry_delivery(actor, log, expected_generation=0)
