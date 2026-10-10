import pytest
from cryptography.fernet import Fernet
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceGrant, User
from apps.accounts.models_social import SocialIdentity
from apps.accounts.mfa_crypto import recovery_codes, totp
from tests.accounts.mfa_helpers import enrolled
from tests.accounts.test_device_auth import attested_login
from tests.accounts.test_social_auth import configure_google, login, mock_claims, nonce
from tests.accounts.oidc_browser_helpers import ORIGIN, make_provider, metadata, start

pytestmark = pytest.mark.django_db
PASSWORD = "Protocol password 843!"


@pytest.fixture(autouse=True)
def encryption(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN, "http://localhost:5173"]
    settings.PLATFORM_STAFF_ORIGINS = [ORIGIN, "http://localhost:5173"]


def person():
    return User.objects.create_user(username="protocol-user", email="protocol@example.test", password=PASSWORD)


def test_google_sign_in_requires_second_factor_even_with_unparsed_idp_amr(monkeypatch):
    user, client = person(), APIClient()
    enrolled(user)
    SocialIdentity.objects.create(user=user, provider="google", provider_sub="google-mfa")
    configure_google()
    mock_claims(monkeypatch, sub="google-mfa", email=user.email)
    first = nonce(client)
    assert first.status_code == 200
    response = login(client, first.data["nonce"])
    assert response.status_code == 200 and response.data["mfa_required"]
    assert "access" not in response.data and "refresh" not in response.data
    assert "refresh_token" not in response.cookies


def test_oidc_browser_callback_requires_local_second_factor(monkeypatch):
    user, client = person(), APIClient()
    enrolled(user)
    SocialIdentity.objects.create(user=user, provider="oidc:campus", provider_sub="oidc-mfa")
    provider = make_provider()
    monkeypatch.setattr("apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider))
    monkeypatch.setattr("apps.accounts.views_oidc_browser.exchange_code", lambda *a, **k: "id-token")
    monkeypatch.setattr("apps.accounts.views_oidc_browser.verify_oidc_token", lambda *a, **k: {
        "sub": "oidc-mfa", "email": user.email, "email_verified": True, "amr": ["mfa"],
    })
    started = start(client)
    assert started.status_code == 200
    response = client.post("/api/v1/auth/social/oidc/callback", {
        "code": "provider-code", "state": started.data["state"], "nonce": started.data["nonce"]},
        format="json", HTTP_ORIGIN=ORIGIN)
    assert response.status_code == 200 and response.data["mfa_required"]
    assert "access" not in response.data and "refresh_token" not in response.cookies


def test_phone_first_factor_is_not_enough_for_an_enrolled_account(monkeypatch):
    user = person()
    enrolled(user)
    monkeypatch.setattr("apps.accounts.views_phone.confirm_login", lambda *a: user)
    response = APIClient().post("/api/v1/auth/phone/login/confirm", {
        "phone": "+14155552671", "code": "123456"}, format="json")
    assert response.status_code == 200 and response.data["mfa_required"]
    assert "access" not in response.data and "refresh_token" not in response.cookies


def test_native_login_waits_for_mfa_then_preserves_device_delivery(settings, monkeypatch):
    user, client = person(), APIClient()
    _, secret = enrolled(user)
    first, _ = attested_login(client, user, settings, monkeypatch, password=PASSWORD)
    assert first.status_code == 200 and first.data["mfa_required"]
    assert "access" not in first.data and not DeviceGrant.objects.filter(user=user).exists()
    second = client.post("/api/v1/auth/mfa/verify", {
        "challenge": first.data["challenge"], "code": totp(secret, int(timezone.now().timestamp() // 30))}, format="json")
    assert second.status_code == 200 and second.data["refresh"] and second.data["device_grant"]
    refreshed = client.post("/api/v1/auth/device/refresh", {"refresh": second.data["refresh"]}, format="json")
    assert refreshed.status_code == 200 and refreshed.data["access"]


def test_browser_challenge_is_bound_to_first_factor_origin():
    user, client = person(), APIClient()
    codes, digests = recovery_codes()
    enrolled(user, recovery_digests=digests)
    first = client.post("/api/v1/auth/login", {
        "username": user.username, "password": PASSWORD, "surface": "member"}, format="json", HTTP_ORIGIN=ORIGIN)
    assert first.status_code == 200
    payload = {"challenge": first.data["challenge"], "code": codes[0], "surface": "staff_api"}
    assert client.post("/api/v1/auth/mfa/verify", payload, format="json",
                       HTTP_ORIGIN="http://localhost:5173").status_code == 401
    completed = client.post("/api/v1/auth/mfa/verify", payload, format="json", HTTP_ORIGIN=ORIGIN)
    assert completed.status_code == 200 and completed.data["surface"] == "member"
