"""SMS cost caps and OTP cooldowns remain enforceable without a live vendor."""

import pytest
from rest_framework.test import APIClient

from apps.accounts import services_phone
from apps.integrations.models_sms import DailyOtpSmsCounter
from apps.makerspaces.limits_reservations import reserve_platform_otp_sms_quota
from tests.return_helpers import make_user

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("suffix", ["", ".managed.example"])
def test_daily_sms_cap_applies_on_self_host_and_managed(settings, suffix):
    settings.PLATFORM_DOMAIN_SUFFIX = suffix
    settings.OTP_SMS_DAILY_CAP = 2
    settings.MANAGED_RESOURCE_LIMITS = {"otp_sms": 1}
    assert reserve_platform_otp_sms_quota() is True
    if not suffix:
        assert reserve_platform_otp_sms_quota() is True
    assert reserve_platform_otp_sms_quota() is False
    assert DailyOtpSmsCounter.objects.get().count == (1 if suffix else 2)


def test_sms_counter_failure_keeps_auth_available(settings, monkeypatch):
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    settings.OTP_SMS_DAILY_CAP = 1
    monkeypatch.setattr(DailyOtpSmsCounter.objects, "get_or_create", lambda **k: (_ for _ in ()).throw(RuntimeError()))
    assert reserve_platform_otp_sms_quota() is True


def test_otp_resend_cooldown_survives_an_unsuccessful_provider(monkeypatch):
    user = make_user("sms-cooldown-user")
    monkeypatch.setattr(services_phone, "send_sms", lambda **k: False)
    challenge, sent = services_phone._issue(user, "+14155550123", "link")
    assert sent is False and challenge.pk is not None
    with pytest.raises(services_phone.ChallengeCooldown):
        services_phone._issue(user, "+14155550123", "link")


def test_phone_request_throttle_returns_429(settings, monkeypatch):
    from apps.accounts.throttles import PhoneOtpRequestThrottle

    monkeypatch.setattr(PhoneOtpRequestThrottle, "rate", "1/min", raising=False)
    monkeypatch.setattr("apps.accounts.views_phone._phone_login_available", lambda: True)
    monkeypatch.setattr("apps.accounts.views_phone.start_login", lambda phone: None)
    client = APIClient()
    assert client.post("/api/v1/auth/phone/login/start", {"phone": "+14155550123"}, format="json").status_code == 200
    assert client.post("/api/v1/auth/phone/login/start", {"phone": "+14155550123"}, format="json").status_code == 429
