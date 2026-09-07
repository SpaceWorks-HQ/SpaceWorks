"""The `webhook` notification channel: signed JSON to the makerspace's own endpoint."""
import hashlib
import hmac
import json

import pytest
from django.urls import reverse

from apps.integrations import webhooks
from apps.integrations.dispatch_channels import _channel_configured, _deliver_notification
from apps.integrations.models import NotificationDeliveryLog, NotificationDestination
from apps.integrations.notification_enums import (
    NotificationDeliveryStatus,
    NotificationFeature,
    NonEmailNotificationChannel,
)
from apps.makerspaces.module_install import install_module
from apps.makerspaces.module_purge_plans import PLANS
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db

SECRET = "correct-horse-battery-staple-32"


def _destination(space, **overrides):
    dest = NotificationDestination(
        makerspace=space, channel="webhook", label=overrides.pop("label", "ERP"),
        is_active=True,
    )
    dest.set_webhook_url(overrides.pop("url", "https://hooks.example.org/spaceworks"))
    if overrides.pop("secret", SECRET):
        dest.set_signing_secret(SECRET)
    dest.save()
    return dest


def _log(space, dest, **fields):
    return NotificationDeliveryLog.objects.create(
        makerspace=space, channel="webhook", destination=dest, destination_label=dest.label,
        feature=NotificationFeature.HARDWARE_REQUESTS, event="request.accepted",
        text_body="Request #12 accepted", payload={"request_id": 12}, **fields,
    )


def test_signature_is_hmac_over_timestamp_dot_body():
    body = b'{"a":1}'
    header = webhooks.sign_webhook_body(SECRET, body, 1_700_000_000)
    assert header.startswith("t=1700000000,v1=")
    expected = hmac.new(SECRET.encode(), b"1700000000." + body, hashlib.sha256).hexdigest()
    assert header == f"t=1700000000,v1={expected}"


def test_delivery_posts_signed_json_and_marks_sent(monkeypatch):
    space = make_space("wh-space")
    if _needs_install(space):
        install_module(space, "webhook", actor=None)
    dest = _destination(space)
    log = _log(space, dest)
    sent = {}

    def fake_deliver(url, payload, extra_headers=None):
        sent["url"], sent["payload"], sent["headers"] = url, payload, extra_headers

    monkeypatch.setattr(webhooks, "_deliver", fake_deliver)
    _deliver_notification(log)
    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.SENT
    assert sent["url"] == "https://hooks.example.org/spaceworks"
    body = json.loads(sent["payload"])
    assert body == {
        "id": log.pk, "event": "request.accepted", "feature": "hardware_requests",
        "makerspace_id": space.pk, "text": "Request #12 accepted", "data": {"request_id": 12},
        "created_at": log.created_at.isoformat(),
    }
    header = sent["headers"][webhooks.SIGNATURE_HEADER]
    t, v1 = header.split(",")
    ts = int(t[2:])
    assert v1 == "v1=" + hmac.new(SECRET.encode(), f"{ts}.".encode() + sent["payload"], hashlib.sha256).hexdigest()
    assert sent["headers"][webhooks.EVENT_HEADER] == "request.accepted"
    assert sent["headers"][webhooks.DELIVERY_HEADER] == str(log.pk)


def _needs_install(space):
    from apps.makerspaces.platform import module_enabled

    return not module_enabled(space, "webhook")


def test_without_a_secret_or_destination_the_channel_is_not_configured():
    space = make_space("wh-unconfigured")
    assert _channel_configured(space, NonEmailNotificationChannel.WEBHOOK) is False
    dest = _destination(space, secret=None)
    assert _channel_configured(space, NonEmailNotificationChannel.WEBHOOK, dest) is False
    dest.set_signing_secret(SECRET)
    dest.save()
    assert _channel_configured(space, NonEmailNotificationChannel.WEBHOOK, dest) is True


def test_failed_delivery_is_recorded_not_raised(monkeypatch):
    space = make_space("wh-fail")
    if _needs_install(space):
        install_module(space, "webhook", actor=None)
    dest = _destination(space)
    log = _log(space, dest)

    def boom(url, payload, extra_headers=None):
        raise webhooks.WebhookDeliveryError("Webhook delivery failed.")

    monkeypatch.setattr(webhooks, "_deliver", boom)
    _deliver_notification(log)
    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.FAILED
    assert log.attempts == 1
    assert "hooks.example.org" not in log.error  # the URL is a secret; never in the error text


def test_module_off_skips_instead_of_sending(monkeypatch):
    from apps.integrations.dispatch_channels import channel_module_blocks
    from apps.makerspaces.platform import module_enabled

    from tests.module_helpers import disable_module

    # The test fixtures give a new makerspace every module; uninstall this one explicitly.
    space = make_space("wh-off")
    disable_module(space, "webhook")
    space.refresh_from_db()
    assert module_enabled(space, "webhook") is False
    assert channel_module_blocks(space, "webhook") is True
    dest = _destination(space)
    log = _log(space, dest)
    monkeypatch.setattr(webhooks, "_deliver", lambda *a, **k: pytest.fail("must not send"))
    _deliver_notification(log)
    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.SKIPPED
    assert log.error == "notification_channel_module_disabled"


def test_staff_api_requires_a_secret_and_never_echoes_it(monkeypatch):
    # The serializer resolves the hostname to refuse private ranges; no DNS in unit tests.
    monkeypatch.setattr(
        "apps.admin_api.serializers_notification_destinations.validate_webhook_url", lambda value: value
    )
    space = make_space("wh-api")
    if _needs_install(space):
        install_module(space, "webhook", actor=None)
    manager = make_member("wh-manager", space)
    client = authenticated_client(manager)
    url = reverse("admin-notification-destinations", kwargs={"makerspace_id": space.pk})
    base = {"channel": "webhook", "label": "ERP", "webhook_url": "https://hooks.example.org/x"}
    refused = client.post(url, base, format="json")
    assert refused.status_code == 400 and "signing_secret" in refused.json()
    created = client.post(url, {**base, "signing_secret": SECRET}, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["signing_secret_set"] is True and body["credential_set"] is True
    assert SECRET not in created.content.decode()
    assert "hooks.example.org" not in created.content.decode()
    # A Slack room must not carry a signing secret.
    slack = client.post(url, {"channel": "slack", "label": "Ops", "webhook_url": "https://hooks.slack.com/services/x", "signing_secret": SECRET}, format="json")
    assert slack.status_code == 400 and "signing_secret" in slack.json()


def test_purge_plan_deletes_only_webhook_destinations():
    space = make_space("wh-purge")
    dest = _destination(space)
    other = NotificationDestination(makerspace=space, channel="slack", label="Ops")
    other.set_webhook_url("https://hooks.slack.com/services/x")
    other.save()
    plan = next(plan for plan in PLANS if plan.key == "webhook")
    plan.delete(space, None)
    assert not NotificationDestination.objects.filter(pk=dest.pk).exists()
    assert NotificationDestination.objects.filter(pk=other.pk).exists()
