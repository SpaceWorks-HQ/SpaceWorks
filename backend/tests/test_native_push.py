import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceGrant
from apps.accounts.services_device_tokens import issue_device_token_pair
from apps.integrations.dispatch_channels import dispatch_channel
from apps.integrations.models import (
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationFeature,
    PlatformPushSettings,
    PushDevice,
)
from apps.integrations.notification_catalog import DEFAULT_CHANNEL_STATE, default_state
from apps.integrations.push_fcm import PushProviderError
from tests.device_helpers import make_native_app_registration
from tests.return_helpers import make_member, make_space


pytestmark = pytest.mark.django_db


def device_client(user, makerspace, *, platform="apple", environment="development"):
    now = timezone.now()
    grant = DeviceGrant.objects.create(
        registration=make_native_app_registration(
            platform=platform,
            environment=environment,
        ),
        user=user,
        platform=platform,
        app_id="org.spaceworks.app",
        signing_identity="TEAM.org.spaceworks.app",
        environment=environment,
        attestation_subject_fingerprint="f" * 64,
        attested_at=now,
        last_used_at=now,
    )
    access, _refresh, _family = issue_device_token_pair(user, grant)
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_X_MAKERSPACE_ID=str(makerspace.id),
    )
    return client, grant


def test_native_push_defaults_off_for_every_feature():
    for feature in DEFAULT_CHANNEL_STATE:
        assert default_state(feature, NotificationChannel.NATIVE_PUSH) is False


def test_push_registration_is_secret_and_idempotent(settings):
    settings.PUSH_TOKEN_HMAC_KEY = "h" * 64
    makerspace = make_space("native-push-register")
    user = make_member("native-push-register-user", makerspace)
    client, grant = device_client(user, makerspace)
    raw_token = "a" * 64
    payload = {
        "token": raw_token,
        "provider": "apns",
        "environment": "development",
    }

    created = client.post("/api/v1/integrations/push/devices", payload, format="json")
    repeated = client.post("/api/v1/integrations/push/devices", payload, format="json")

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert created.data["id"] == repeated.data["id"]
    assert "token" not in created.data
    assert PushDevice.objects.count() == 1
    device = PushDevice.objects.get()
    assert device.device_grant == grant
    assert raw_token not in device.token_ciphertext
    assert device.get_token() == raw_token
    assert device.token_fingerprint != raw_token


def test_push_registration_requires_matching_attested_identity(settings):
    settings.PUSH_TOKEN_HMAC_KEY = "h" * 64
    makerspace = make_space("native-push-identity")
    user = make_member("native-push-identity-user", makerspace)
    client, _grant = device_client(user, makerspace, platform="android")

    response = client.post(
        "/api/v1/integrations/push/devices",
        {
            "token": "b" * 64,
            "provider": "apns",
            "environment": "development",
        },
        format="json",
    )

    assert response.status_code == 403
    assert not PushDevice.objects.exists()


def test_push_device_delete_is_owner_only(settings):
    settings.PUSH_TOKEN_HMAC_KEY = "h" * 64
    makerspace = make_space("native-push-owner")
    owner = make_member("native-push-owner-user", makerspace)
    other = make_member("native-push-other-user", makerspace)
    owner_client, _ = device_client(owner, makerspace)
    other_client, _ = device_client(other, makerspace)
    created = owner_client.post(
        "/api/v1/integrations/push/devices",
        {
            "token": "c" * 64,
            "provider": "apns",
            "environment": "development",
        },
        format="json",
    )

    denied = other_client.delete(
        f"/api/v1/integrations/push/devices/{created.data['id']}"
    )

    assert denied.status_code == 404
    assert PushDevice.objects.get(pk=created.data["id"]).active is True


def test_missing_platform_credentials_are_inert():
    makerspace = make_space("native-push-inert")

    [log] = dispatch_channel(
        makerspace=makerspace,
        channel=NotificationChannel.NATIVE_PUSH,
        feature=NotificationFeature.HARDWARE_REQUESTS,
        event="submitted",
        text_body="Request submitted",
        sync=True,
    )

    assert log.status == NotificationDeliveryStatus.FAILED
    assert log.error == "notification_channel_not_configured"


def test_invalid_provider_token_is_deactivated_without_leaking_token(
    settings, monkeypatch
):
    settings.PUSH_TOKEN_HMAC_KEY = "h" * 64
    makerspace = make_space("native-push-invalid")
    user = make_member("native-push-invalid-user", makerspace)
    client, _ = device_client(user, makerspace, platform="android")
    raw_token = "d" * 64
    registered = client.post(
        "/api/v1/integrations/push/devices",
        {
            "token": raw_token,
            "provider": "fcm",
            "environment": "development",
        },
        format="json",
    )
    assert registered.status_code == 201
    platform = PlatformPushSettings.load()
    platform.set_fcm_service_account('{"configured": true}')
    platform.save()

    def invalid(*args, **kwargs):
        raise PushProviderError("provider detail containing secret", invalid_token=True)

    monkeypatch.setattr("apps.integrations.push.send_fcm", invalid)
    [log] = dispatch_channel(
        makerspace=makerspace,
        channel=NotificationChannel.NATIVE_PUSH,
        feature=NotificationFeature.HARDWARE_REQUESTS,
        event="submitted",
        text_body="Request submitted",
        sync=True,
    )

    device = PushDevice.objects.get(pk=registered.data["id"])
    assert device.active is False
    assert device.invalidated_at is not None
    assert log.status == NotificationDeliveryStatus.SENT
    assert raw_token not in log.error
    assert raw_token not in str(log.payload)
