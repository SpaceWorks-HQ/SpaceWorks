import json
from datetime import timedelta
from io import BytesIO

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import DeviceGrant, User
from apps.accounts.models_social import (
    PlatformSocialAuthSettings,
    SocialIdentity,
)
from apps.accounts.social_google import verify_google_token
from apps.accounts.social_jwt import SocialTokenError
from apps.accounts.services_device_tokens import issue_device_token_pair
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.device_helpers import make_native_app_registration
from tests.return_helpers import make_member, make_space, make_user


pytestmark = pytest.mark.django_db

ORIGIN = "http://localhost:5173"
NONCE_URL = "/api/v1/auth/social/nonce"
GOOGLE_URL = "/api/v1/auth/social/google"


def configure_google():
    row = PlatformSocialAuthSettings.load()
    row.google_web_client_id = "google-web-client"
    row.google_ios_client_id = "google-ios-client"
    row.google_android_client_id = "google-android-client"
    row.save()
    return row


def nonce(client, *, surface="member", origin=ORIGIN):
    return client.post(
        NONCE_URL,
        {
            "provider": "google",
            "surface": surface,
            "delivery": "web",
            "client_platform": "web",
        },
        format="json",
        HTTP_ORIGIN=origin,
    )


def login(client, raw_nonce, *, surface="member", origin=ORIGIN):
    return client.post(
        GOOGLE_URL,
        {
            "id_token": "provider-token-secret",
            "nonce": raw_nonce,
            "surface": surface,
            "delivery": "web",
            "client_platform": "web",
        },
        format="json",
        HTTP_ORIGIN=origin,
    )


def mock_claims(monkeypatch, *, sub="google-sub", email="person@example.test", verified=True, name="Person"):
    monkeypatch.setattr(
        "apps.accounts.views_social._verify",
        lambda *args, **kwargs: {
            "sub": sub,
            "email": email,
            "email_verified": verified,
            "name": name,
        },
    )


def test_unconfigured_social_auth_is_hidden_and_provider_route_is_404():
    config = APIClient().get("/api/v1/config")
    unavailable = nonce(APIClient())

    assert config.status_code == 200
    assert "social_auth" not in config.data
    assert unavailable.status_code == 404
    assert unavailable.data["code"] == "social_unavailable"


def test_config_exposes_only_frontend_safe_provider_ids():
    row = configure_google()
    row.apple_service_id = "org.spaceworks.web"
    row.set_apple_private_key("-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----")
    row.save()

    response = APIClient().get("/api/v1/config")

    assert response.data["social_auth"] == {
        "google": {"enabled": True, "web_client_id": "google-web-client"},
        "apple": {"enabled": True, "service_id": "org.spaceworks.web"},
    }
    assert "secret" not in str(response.data)


def test_member_social_login_creates_global_user_and_surface_cookie(monkeypatch):
    configure_google()
    mock_claims(monkeypatch)
    challenge = nonce(APIClient())
    assert challenge.status_code == 200

    response = login(APIClient(), challenge.data["nonce"])

    assert response.status_code == 200
    assert set(response.data) == {"access", "user", "outcome"}
    assert response.data["outcome"] == "created"
    identity = SocialIdentity.objects.select_related("user").get()
    assert identity.provider_sub == "google-sub"
    assert identity.user.email == "person@example.test"
    assert identity.user.email_verified_at is not None
    assert not identity.user.has_usable_password()
    refresh = RefreshToken(response.cookies["refresh_token"].value)
    assert refresh["surface"] == "member"
    assert "provider-token-secret" not in str(response.data)


def test_verified_provider_only_auto_links_verified_local_account(monkeypatch):
    configure_google()
    local = make_user(
        "social-existing",
        email_verified_at=None,
        access_status=User.AccessStatus.ACTIVE,
    )
    local.email = "person@example.test"
    local.save(update_fields=["email"])
    mock_claims(monkeypatch)
    first_nonce = nonce(APIClient()).data["nonce"]

    blocked = login(APIClient(), first_nonce)

    assert blocked.status_code == 409
    assert blocked.data["code"] == "account_link_required"
    assert not SocialIdentity.objects.exists()

    local.email_verified_at = timezone.now()
    local.save(update_fields=["email_verified_at"])
    linked = login(APIClient(), nonce(APIClient()).data["nonce"])
    assert linked.status_code == 200
    assert linked.data["outcome"] == "auto_linked"
    assert SocialIdentity.objects.get().user == local


def test_staff_social_login_requires_trusted_origin_and_existing_authority(monkeypatch):
    configure_google()
    settings_origin = "https://staff-social.example.test"
    makerspace = make_space("staff-social")
    makerspace.frontend_domain = "staff-social.example.test"
    makerspace.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    makerspace.save(update_fields=["frontend_domain", "frontend_domain_status"])
    user = make_member("staff-social-user", makerspace)
    user.email = "person@example.test"
    user.save(update_fields=["email"])
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    mock_claims(monkeypatch)

    public_only = "https://public-client.example.test"
    makerspace.cors_allowed_origins = [public_only]
    makerspace.save(update_fields=["cors_allowed_origins"])
    assert nonce(APIClient(), surface="staff", origin=public_only).status_code == 403

    raw = nonce(APIClient(), surface="staff", origin=settings_origin)
    response = login(
        APIClient(), raw.data["nonce"], surface="staff", origin=settings_origin
    )

    assert response.status_code == 200
    assert response.data["outcome"] == "auto_linked"
    assert RefreshToken(response.cookies["refresh_token"].value)["surface"] == "staff"
    assert [row["id"] for row in response.data["user"]["makerspaces"]] == [makerspace.pk]


def test_staff_social_login_never_creates_account(monkeypatch, settings):
    configure_google()
    settings.PLATFORM_STAFF_ORIGINS = [ORIGIN]
    mock_claims(monkeypatch, email="missing@example.test")
    challenge = nonce(APIClient(), surface="staff")

    response = login(APIClient(), challenge.data["nonce"], surface="staff")

    assert response.status_code == 403
    assert response.data["code"] == "staff_access_required"
    assert not User.objects.filter(email="missing@example.test").exists()


def test_member_surface_token_cannot_call_staff_api_without_origin(monkeypatch):
    configure_google()
    mock_claims(monkeypatch)
    response = login(APIClient(), nonce(APIClient()).data["nonce"])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    denied = client.get("/api/v1/admin/makerspaces")

    assert denied.status_code == 403


def test_nonce_is_single_use_and_origin_bound(monkeypatch):
    configure_google()
    mock_claims(monkeypatch)
    raw = nonce(APIClient()).data["nonce"]

    wrong_origin = login(APIClient(), raw, origin="http://127.0.0.1:5000")
    replay = login(APIClient(), raw)

    assert wrong_origin.status_code == 401
    assert replay.status_code == 401
    assert not SocialIdentity.objects.exists()


def test_explicit_link_never_email_matches_and_last_credential_is_protected(monkeypatch):
    configure_google()
    user = make_user("social-link-user", access_status=User.AccessStatus.ACTIVE)
    client = APIClient()
    client.force_authenticate(user)
    mock_claims(monkeypatch, email="someone-else@example.test")
    raw = nonce(client).data["nonce"]

    linked = client.post(
        "/api/v1/auth/social/providers",
        {
            "provider": "google",
            "id_token": "secret-token",
            "nonce": raw,
            "client_platform": "web",
        },
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert linked.status_code == 200
    assert SocialIdentity.objects.get().user == user
    assert "provider_sub" not in linked.data

    user.set_unusable_password()
    user.save(update_fields=["password"])
    blocked = client.delete("/api/v1/auth/social/providers/google")
    assert blocked.status_code == 409
    assert blocked.data["code"] == "last_credential"


def test_google_jwt_verifier_checks_signature_issuer_audience_and_nonce(
    settings, monkeypatch
):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-key"
    body = json.dumps({"keys": [public_jwk]}).encode()

    class Response:
        status_code = 200
        headers = {"Content-Length": str(len(body))}
        raw = BytesIO(body)

    monkeypatch.setattr("apps.accounts.social_jwt.requests.get", lambda *a, **k: Response())
    settings.SOCIAL_GOOGLE_JWKS_URL = "https://fixed.example.test/jwks"
    now = timezone.now()
    token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": "google-web-client",
            "sub": "signed-sub",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "nonce": "expected-nonce",
            "email": "signed@example.test",
            "email_verified": True,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    claims = verify_google_token(
        token, nonce="expected-nonce", audience="google-web-client"
    )
    assert claims["sub"] == "signed-sub"
    with pytest.raises(SocialTokenError):
        verify_google_token(token, nonce="wrong", audience="google-web-client")
    with pytest.raises(SocialTokenError):
        verify_google_token(token, nonce="expected-nonce", audience="wrong-client")


def test_platform_settings_api_keeps_apple_key_write_only():
    superuser = make_user(
        "social-settings-root",
        is_superuser=True,
        is_staff=True,
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(superuser)

    updated = client.patch(
        "/api/v1/admin/platform/social-auth-settings",
        {
            "google_web_client_id": "google-web",
            "apple_service_id": "apple-service",
            "apple_native_app_ids": ["org.spaceworks.ios"],
            "apple_team_id": "TEAMID",
            "apple_key_id": "KEYID",
            "apple_private_key": "private-key-secret",
        },
        format="json",
    )

    assert updated.status_code == 200
    assert updated.data["apple_private_key_set"] is True
    assert "apple_private_key" not in updated.data
    row = PlatformSocialAuthSettings.objects.get()
    assert "private-key-secret" not in row.apple_private_key
    assert row.get_apple_private_key() == "private-key-secret"


def test_social_csp_is_unchanged_when_dormant_and_exact_when_configured():
    from apps.accounts.social_csp import clear_social_csp_cache

    clear_social_csp_cache()
    dormant = APIClient().get("/")["Content-Security-Policy"]
    assert "accounts.google.com" not in dormant
    assert "appleid.apple.com" not in dormant

    row = PlatformSocialAuthSettings.load()
    row.google_web_client_id = "google-web"
    row.apple_service_id = "apple-service"
    row.save()
    clear_social_csp_cache()
    configured = APIClient().get("/")["Content-Security-Policy"]
    assert "https://accounts.google.com" in configured
    assert "https://appleid.cdn-apple.com" in configured
    assert "https://appleid.apple.com" in configured


def test_member_refresh_rejects_public_api_client_origin(monkeypatch):
    configure_google()
    mock_claims(monkeypatch)
    response = login(APIClient(), nonce(APIClient()).data["nonce"])
    public_origin = "https://public-api-client.example.test"
    makerspace = make_space("social-refresh-public")
    makerspace.cors_allowed_origins = [public_origin]
    makerspace.save(update_fields=["cors_allowed_origins"])
    client = APIClient()
    client.cookies["refresh_token"] = response.cookies["refresh_token"].value

    denied = client.post(
        "/api/v1/auth/refresh",
        HTTP_ORIGIN=public_origin,
        HTTP_X_REFRESH_CSRF="1",
    )

    assert denied.status_code == 403


def test_apple_first_login_name_is_only_used_for_created_user(monkeypatch):
    row = PlatformSocialAuthSettings.load()
    row.apple_service_id = "org.spaceworks.web"
    row.save()
    monkeypatch.setattr(
        "apps.accounts.views_social._verify",
        lambda *args, **kwargs: {
            "sub": "apple-relay-sub",
            "email": "relay@privaterelay.appleid.com",
            "email_verified": True,
            "name": "",
        },
    )
    challenge = APIClient().post(
        NONCE_URL,
        {"provider": "apple", "surface": "member", "delivery": "web", "client_platform": "web"},
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )
    response = APIClient().post(
        "/api/v1/auth/social/apple",
        {
            "id_token": "apple-secret-token",
            "nonce": challenge.data["nonce"],
            "surface": "member",
            "delivery": "web",
            "client_platform": "web",
            "apple_name": "First Apple Name",
        },
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )

    assert response.status_code == 200
    user = SocialIdentity.objects.get().user
    assert user.display_name == "First Apple Name"
    user.display_name = "Chosen Name"
    user.save(update_fields=["display_name"])
    second = APIClient().post(
        NONCE_URL,
        {"provider": "apple", "surface": "member", "delivery": "web", "client_platform": "web"},
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )
    response = APIClient().post(
        "/api/v1/auth/social/apple",
        {"id_token": "apple-secret-token", "nonce": second.data["nonce"], "surface": "member", "delivery": "web", "client_platform": "web", "apple_name": "Overwrite Attempt"},
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.display_name == "Chosen Name"


def test_device_social_login_reuses_attested_device_grant_format(monkeypatch):
    configure_google()
    user = make_user(
        "social-device-user",
        access_status=User.AccessStatus.ACTIVE,
        email_verified_at=timezone.now(),
    )
    now = timezone.now()
    grant = DeviceGrant.objects.create(
        registration=make_native_app_registration(),
        user=user,
        platform="apple",
        app_id="org.spaceworks.app",
        signing_identity="TEAM.org.spaceworks.app",
        environment="development",
        attestation_subject_fingerprint="f" * 64,
        attested_at=now,
        last_used_at=now,
    )
    access, _refresh, _family = issue_device_token_pair(user, grant)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    mock_claims(
        monkeypatch,
        sub="device-social-sub",
        email=user.email,
        verified=True,
    )
    challenge = client.post(
        NONCE_URL,
        {"provider": "google", "surface": "member", "delivery": "device", "client_platform": "ios"},
        format="json",
    )
    response = client.post(
        GOOGLE_URL,
        {"id_token": "device-provider-token", "nonce": challenge.data["nonce"], "surface": "member", "delivery": "device", "client_platform": "ios"},
        format="json",
    )

    assert response.status_code == 200
    assert set(response.data) == {
        "access", "refresh", "user", "outcome", "device_grant"
    }
    claims = jwt.decode(
        response.data["access"], options={"verify_signature": False}
    )
    assert claims["device_grant_id"] == str(grant.pk)
    assert "surface" not in claims
