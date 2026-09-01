import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.accounts.models import DeviceGrant, User
from apps.accounts.services_tokens import blacklist_outstanding_tokens
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from tests.device_helpers import make_native_app_registration
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db

CHALLENGE = "/api/v1/auth/device/attestation-challenge"
LOGIN = "/api/v1/auth/device/login"
REFRESH = "/api/v1/auth/device/refresh"
BROWSER_REFRESH = "/api/v1/auth/refresh"
ME = "/api/v1/auth/me"


def configure_apple(settings):
    settings.DEVICE_ATTESTATION_APPS = {
        "apple": {
            "org.spaceworks.app": {
                "signing_identity": "TEAMID.org.spaceworks.app",
                "environments": ["development"],
            }
        }
    }
    settings.DEVICE_APPLE_ATTESTATION_VERIFY_URL = "https://attest.example.test/verify"
    settings.DEVICE_APPLE_ATTESTATION_VERIFY_TOKEN = "provider-secret"
    return make_native_app_registration()


def mock_apple_provider(monkeypatch, challenge):
    class ProviderResponse:
        status_code = 200

        def json(self):
            return {
                "verified": True,
                "subject": "app-attest-key-123",
                "platform": "apple",
                "app_id": "org.spaceworks.app",
                "signing_identity": "TEAMID.org.spaceworks.app",
                "environment": "development",
                "challenge": challenge,
            }

    monkeypatch.setattr(
        "apps.accounts.attestation_apple.requests.post",
        lambda *args, **kwargs: ProviderResponse(),
    )


def attested_login(client, user, settings, monkeypatch):
    configure_apple(settings)
    challenge_response = client.post(
        CHALLENGE,
        {
            "platform": "apple",
            "app_id": "org.spaceworks.app",
            "environment": "development",
        },
        format="json",
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.data["challenge"]

    mock_apple_provider(monkeypatch, challenge)
    payload = {
        "username": user.username,
        "password": "strong-device-password",
        "platform": "apple",
        "app_id": "org.spaceworks.app",
        "environment": "development",
        "challenge": challenge,
        "attestation": {"assertion": "opaque-provider-payload"},
    }
    response = client.post(LOGIN, payload, format="json")
    return response, payload


def test_device_routes_are_dormant_until_attestation_is_configured(settings):
    settings.DEVICE_ATTESTATION_APPS = {}

    response = APIClient().post(
        CHALLENGE,
        {
            "platform": "apple",
            "app_id": "org.spaceworks.app",
            "environment": "development",
        },
        format="json",
    )

    assert response.status_code == 503
    assert response.data["code"] == "attestation_unavailable"


def test_attested_login_is_one_time_and_returns_only_active_visible_memberships(
    settings, monkeypatch
):
    user = make_user(
        "native-login-user",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    visible = make_space("native-visible")
    archived = make_space("native-archived")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    MakerspaceMembership.objects.create(user=user, makerspace=visible)
    MakerspaceMembership.objects.create(user=user, makerspace=archived)

    client = APIClient()
    response, payload = attested_login(client, user, settings, monkeypatch)

    assert response.status_code == 200
    assert set(response.data) == {"access", "refresh", "user", "device_grant"}
    assert [row["id"] for row in response.data["user"]["makerspaces"]] == [visible.id]
    grant = DeviceGrant.objects.get(pk=response.data["device_grant"]["id"])
    assert grant.attestation_subject_fingerprint != "app-attest-key-123"

    replay = client.post(LOGIN, payload, format="json")
    assert replay.status_code == 401
    assert DeviceGrant.objects.filter(user=user).count() == 1


def test_device_auth_routes_reject_browser_transport(settings):
    configure_apple(settings)
    response = APIClient().post(
        CHALLENGE,
        {
            "platform": "apple",
            "app_id": "org.spaceworks.app",
            "environment": "development",
        },
        format="json",
        HTTP_ORIGIN="https://app.example.test",
    )
    assert response.status_code == 403


def test_refresh_reuse_revokes_entire_device_grant(settings, monkeypatch):
    user = make_user(
        "native-refresh-user",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    response, _ = attested_login(APIClient(), user, settings, monkeypatch)
    assert response.status_code == 200
    original_refresh = response.data["refresh"]

    rotated = APIClient().post(REFRESH, {"refresh": original_refresh}, format="json")
    assert rotated.status_code == 200
    replay = APIClient().post(REFRESH, {"refresh": original_refresh}, format="json")

    assert replay.status_code == 401
    grant = DeviceGrant.objects.get(pk=response.data["device_grant"]["id"])
    assert grant.status == DeviceGrant.Status.REVOKED
    assert grant.refresh_families.get().reuse_detected_at is not None
    assert APIClient().post(
        REFRESH, {"refresh": rotated.data["refresh"]}, format="json"
    ).status_code == 401


def test_browser_refresh_rejects_device_token_without_minting(
    settings, monkeypatch
):
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5000"]
    user = make_user(
        "native-wrong-refresh-route",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    login, _ = attested_login(APIClient(), user, settings, monkeypatch)
    assert login.status_code == 200
    device_refresh = login.data["refresh"]
    token_count = OutstandingToken.objects.filter(user=user).count()

    browser = APIClient()
    browser.cookies["refresh_token"] = device_refresh
    rejected = browser.post(
        BROWSER_REFRESH,
        HTTP_X_REFRESH_CSRF="1",
        HTTP_ORIGIN="http://localhost:5000",
    )

    assert rejected.status_code == 401
    assert rejected.data["detail"] == (
        "Device refresh tokens must use the device refresh endpoint."
    )
    assert "access" not in rejected.data
    assert "refresh_token" not in rejected.cookies
    assert OutstandingToken.objects.filter(user=user).count() == token_count
    assert AuditLog.objects.filter(
        action="auth.refresh_rejected",
        actor=user,
        meta__reason="device_refresh_wrong_endpoint",
    ).exists()

    rotated = APIClient().post(
        REFRESH, {"refresh": device_refresh}, format="json"
    )
    assert rotated.status_code == 200
    assert rotated.data["refresh"] != device_refresh


def test_password_invalidation_revokes_native_access(settings, monkeypatch):
    user = make_user(
        "native-password-user",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    response, _ = attested_login(APIClient(), user, settings, monkeypatch)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert client.get(ME).status_code == 200

    blacklist_outstanding_tokens(user)

    assert client.get(ME).status_code == 401
    assert DeviceGrant.objects.get(user=user).status == DeviceGrant.Status.REVOKED


def test_ordinary_browser_jwt_cannot_select_native_makerspace():
    user = make_user(
        "browser-header-user",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    makerspace = make_space("browser-header-space")
    MakerspaceMembership.objects.create(user=user, makerspace=makerspace)
    login = APIClient().post(
        "/api/v1/auth/login",
        {"username": user.username, "password": "strong-device-password"},
        format="json",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    response = client.get(ME, HTTP_X_MAKERSPACE_ID=str(makerspace.id))

    assert response.status_code == 403


def test_native_makerspace_header_rechecks_membership_on_every_request(
    settings, monkeypatch
):
    user = make_user(
        "native-scope-user",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    makerspace = make_space("native-scope-space")
    membership = MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace
    )
    login, _ = attested_login(APIClient(), user, settings, monkeypatch)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    allowed = client.get(ME, HTTP_X_MAKERSPACE_ID=str(makerspace.pk))
    assert allowed.status_code == 200
    assert [row["id"] for row in allowed.data["makerspaces"]] == [makerspace.pk]

    membership.status = "revoked"
    membership.save(update_fields=["status"])
    assert client.get(
        ME, HTTP_X_MAKERSPACE_ID=str(makerspace.pk)
    ).status_code == 403
