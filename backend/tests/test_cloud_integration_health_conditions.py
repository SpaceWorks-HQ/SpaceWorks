"""Health status reflects effective credentials and scoped native delivery failures."""

import pytest

from apps.integrations.health import build_integration_health
from apps.integrations.models import (
    NotificationDeliveryLog, NotificationDeliveryStatus, NotificationFeature,
    PlatformEmailSettings,
)
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db


def test_platform_smtp_fallback_is_visible_and_unreadable_tenant_password_is_not():
    space = make_space("health-smtp-fallback")
    platform = PlatformEmailSettings.load()
    platform.smtp_host = "smtp.example.org"
    platform.save()
    assert build_integration_health(space)["smtp"]["configured"] is True
    space.smtp_host = "smtp.tenant.example"
    space.smtp_password = "fernet:unreadable"
    space.save()
    assert build_integration_health(space)["smtp"] == {"status": "warn", "configured": False}


def test_native_push_failure_is_scoped_and_contains_no_credentials(monkeypatch):
    own, other = make_space("health-push-own"), make_space("health-push-other")
    monkeypatch.setattr("apps.integrations.push.push_configured", lambda: True)
    for space, error in [(own, "notification_delivery_failed:PushProviderError"), (other, "other-space")]:
        NotificationDeliveryLog.objects.create(
            makerspace=space, channel="native_push", feature=NotificationFeature.HARDWARE_REQUESTS,
            event="accepted", status=NotificationDeliveryStatus.FAILED, error=error,
        )
    health = build_integration_health(own)
    assert health["status"] == "warn"
    assert health["native_push"]["configured"] is True
    assert health["native_push"]["failed"] == 1
    assert health["native_push"]["last_failure"]["error"].endswith("PushProviderError")
    assert "other-space" not in str(health)


def test_sms_unconfigured_and_health_errors_do_not_disclose_exception_text(monkeypatch):
    space = make_space("health-provider-error")

    def fail():
        raise RuntimeError("secret-auth-token")

    monkeypatch.setattr("apps.integrations.sms.sms_configured", fail)
    health = build_integration_health(space)
    assert health["sms"] == {"status": "unknown", "detail": "RuntimeError"}
    assert health["status"] == "warn"
    assert "secret-auth-token" not in str(health)


def test_unreadable_destination_credentials_are_reported_unconfigured():
    from apps.integrations.models import NotificationDestination

    space = make_space("health-broken-room")
    destination = NotificationDestination.objects.create(
        makerspace=space, channel="slack", label="Front desk", webhook_url="fernet:private-broken-value",
    )
    section = build_integration_health(space)["chat_destinations"]
    assert section["destinations"][0]["id"] == destination.pk
    assert section["destinations"][0]["configured"] is False
    assert "private-broken-value" not in str(section)


def test_naive_worker_heartbeat_is_normalized_to_utc():
    from apps.integrations.health import _parse_cached_datetime

    parsed = _parse_cached_datetime("2026-10-10T00:00:00")
    assert parsed.utcoffset().total_seconds() == 0
