import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient

from apps.accounts.models import DeviceGrant, NativeAppRegistration, User
from apps.accounts.services_device_tokens import rotate_device_refresh
from tests.accounts.test_device_auth import (
    CHALLENGE,
    LOGIN,
    ME,
    REFRESH,
    attested_login,
    configure_apple,
    mock_apple_provider,
)
from tests.device_helpers import make_native_app_registration
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def _login_payload(user, challenge):
    return {
        "username": user.username,
        "password": "strong-device-password",
        "platform": "apple",
        "app_id": "org.spaceworks.app",
        "environment": "development",
        "challenge": challenge,
        "attestation": {"assertion": "opaque-provider-payload"},
    }


def _challenge(client):
    response = client.post(
        CHALLENGE,
        {
            "platform": "apple",
            "app_id": "org.spaceworks.app",
            "environment": "development",
        },
        format="json",
    )
    assert response.status_code == 200
    return response.data["challenge"]


def test_approved_registration_permits_login_and_refresh(settings, monkeypatch):
    user = make_user(
        "native-approved-registration",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )

    login, _ = attested_login(APIClient(), user, settings, monkeypatch)
    assert login.status_code == 200
    rotated = APIClient().post(
        REFRESH,
        {"refresh": login.data["refresh"]},
        format="json",
    )

    assert rotated.status_code == 200
    grant = DeviceGrant.objects.select_related("registration").get(user=user)
    assert grant.registration.status == NativeAppRegistration.Status.APPROVED


def test_revoked_registration_immediately_blocks_access_and_device_refresh(
    settings, monkeypatch
):
    user = make_user(
        "native-revoked-registration",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    login, _ = attested_login(APIClient(), user, settings, monkeypatch)
    grant = DeviceGrant.objects.select_related("registration").get(user=user)
    NativeAppRegistration.objects.filter(pk=grant.registration_id).update(
        status=NativeAppRegistration.Status.REVOKED,
        revoked_at=timezone.now(),
    )

    access_client = APIClient()
    access_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    assert access_client.get(ME).status_code == 401
    with pytest.raises(AuthenticationFailed):
        rotate_device_refresh(login.data["refresh"])


def test_pending_registration_cannot_create_grant(settings, monkeypatch):
    user = make_user(
        "native-pending-registration",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    registration = configure_apple(settings)
    client = APIClient()
    challenge = _challenge(client)
    mock_apple_provider(monkeypatch, challenge)
    registration.status = NativeAppRegistration.Status.PENDING
    registration.save(update_fields=["status"])

    response = client.post(
        LOGIN,
        _login_payload(user, challenge),
        format="json",
    )

    assert response.status_code == 401
    assert not DeviceGrant.objects.filter(user=user).exists()


def test_registration_uniqueness_distinguishes_global_and_tenant_scope():
    make_native_app_registration()
    with pytest.raises(IntegrityError), transaction.atomic():
        NativeAppRegistration.objects.create(
            app_id="org.spaceworks.app",
            platform="apple",
            environment="development",
            verifier_config_key="duplicate-global",
        )

    first_space = make_space("native-registration-one")
    second_space = make_space("native-registration-two")
    make_native_app_registration(makerspace=first_space)
    make_native_app_registration(makerspace=second_space)
    with pytest.raises(IntegrityError), transaction.atomic():
        NativeAppRegistration.objects.create(
            makerspace=first_space,
            app_id="org.spaceworks.app",
            platform="apple",
            environment="development",
            verifier_config_key="duplicate-tenant",
        )

    assert NativeAppRegistration.objects.count() == 3


def test_challenge_registration_cannot_be_rebound_during_grant_creation(
    settings, monkeypatch
):
    user = make_user(
        "native-registration-binding",
        password="strong-device-password",
        access_status=User.AccessStatus.ACTIVE,
    )
    registration_a = configure_apple(settings)
    client = APIClient()
    challenge = _challenge(client)
    registration_b = make_native_app_registration(
        makerspace=make_space("native-registration-binding")
    )
    mock_apple_provider(monkeypatch, challenge)

    response = client.post(
        LOGIN,
        _login_payload(user, challenge),
        format="json",
    )

    assert response.status_code == 200
    grant = DeviceGrant.objects.get(user=user)
    assert grant.registration_id == registration_a.pk
    assert grant.registration_id != registration_b.pk
