from decimal import Decimal

import pytest
from django.contrib import admin
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.payments.models import Payment, PlatformStripeConnectSettings
from apps.payments.services import mark_offline
from tests.payments.test_machine_payments import service_request
from tests.return_helpers import make_member, make_space, make_user


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fail_closed_checkout_session_lookup(monkeypatch):
    monkeypatch.setattr(
        "apps.payments.stripe_client.checkout_session_is_closed",
        lambda *_args: False,
    )


def pending_connect_settings(slug):
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space(slug)
    member = make_member(f"{slug}-member", makerspace)
    Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=service_request(makerspace, member).id,
        member=member,
        amount=Decimal("2.00"),
        currency="usd",
        created_by=member,
        stripe_provider=Payment.StripeProvider.CONNECT,
        stripe_connected_account_id="acct_pending",
        stripe_checkout_session_id=f"cs_{slug}",
    )
    superadmin = make_user(
        f"{slug}-admin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
        is_staff=True,
    )
    return platform, superadmin


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stripe_secret_key", "sk_rotated"),
        ("stripe_secret_key", ""),
        ("stripe_webhook_secret", "whsec_rotated"),
        ("stripe_webhook_secret", ""),
    ],
)
def test_api_blocks_platform_credential_mutation_with_pending_connect_session(
    settings, field, value
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    platform, superadmin = pending_connect_settings(
        f"platform-api-{field.removeprefix('stripe_')[:7]}-{bool(value)}"
    )
    client = APIClient()
    client.force_authenticate(superadmin)

    response = client.patch(
        "/api/v1/admin/platform/payment-settings",
        {field: value},
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 400
    assert "pending" in str(response.data[field]).lower()
    platform.refresh_from_db()
    assert platform.get_stripe_secret_key() == "sk_platform"
    assert platform.get_stripe_webhook_secret() == "whsec_platform"


def test_api_preserves_omitted_platform_credentials_with_pending_session(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    platform, superadmin = pending_connect_settings("platform-api-omit")
    client = APIClient()
    client.force_authenticate(superadmin)

    response = client.patch(
        "/api/v1/admin/platform/payment-settings",
        {"application_fee_bps": 275},
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200
    platform.refresh_from_db()
    assert platform.application_fee_bps == 275
    assert platform.get_stripe_secret_key() == "sk_platform"
    assert platform.get_stripe_webhook_secret() == "whsec_platform"


@pytest.mark.parametrize("value", ["sk_rotated_after_failure", ""])
def test_failed_connect_expiry_keeps_platform_secret_rotation_and_clear_blocked(
    settings, monkeypatch, value
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    platform, superadmin = pending_connect_settings(
        f"platform-expiry-failed-{bool(value)}"
    )
    payment = Payment.objects.get(stripe_provider=Payment.StripeProvider.CONNECT)
    monkeypatch.setattr(
        "apps.payments.services_checkout.stripe_client.expire_checkout_session",
        lambda *_args: False,
    )

    mark_offline(payment, payment.member)
    client = APIClient()
    client.force_authenticate(superadmin)
    response = client.patch(
        "/api/v1/admin/platform/payment-settings",
        {"stripe_secret_key": value},
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 400
    platform.refresh_from_db()
    assert platform.get_stripe_secret_key() == "sk_platform"


def test_successful_connect_expiry_allows_platform_secret_rotation(
    settings, monkeypatch
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    platform, superadmin = pending_connect_settings("platform-expiry-succeeded")
    payment = Payment.objects.get(stripe_provider=Payment.StripeProvider.CONNECT)
    monkeypatch.setattr(
        "apps.payments.services_checkout.stripe_client.expire_checkout_session",
        lambda *_args: True,
    )

    mark_offline(payment, payment.member)
    client = APIClient()
    client.force_authenticate(superadmin)
    response = client.patch(
        "/api/v1/admin/platform/payment-settings",
        {"stripe_secret_key": "sk_rotated_after_expiry"},
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200
    payment.refresh_from_db()
    platform.refresh_from_db()
    assert payment.stripe_checkout_session_expired_at is not None
    assert platform.get_stripe_secret_key() == "sk_rotated_after_expiry"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stripe_secret_key", "sk_rotated"),
        ("stripe_webhook_secret", "whsec_rotated"),
    ],
)
def test_admin_blocks_platform_credential_change_with_pending_session(field, value):
    platform, _ = pending_connect_settings(f"platform-admin-{field}")
    form_class = admin.site._registry[PlatformStripeConnectSettings].form
    data = {
        "stripe_publishable_key": "",
        "stripe_secret_key": "",
        "stripe_webhook_secret": "",
        "stripe_connect_client_id": "ca_platform",
        "application_fee_bps": 0,
    }
    data[field] = value

    form = form_class(data=data, instance=platform)

    assert not form.is_valid()
    assert "pending" in str(form.errors[field]).lower()


def test_admin_preserves_blank_platform_credentials_with_pending_session():
    platform, _ = pending_connect_settings("platform-admin-omit")
    form_class = admin.site._registry[PlatformStripeConnectSettings].form
    form = form_class(
        data={
            "stripe_publishable_key": "",
            "stripe_secret_key": "",
            "stripe_webhook_secret": "",
            "stripe_connect_client_id": "ca_platform",
            "application_fee_bps": 300,
        },
        instance=platform,
    )

    assert form.is_valid(), form.errors
    form.save()
    platform.refresh_from_db()
    assert platform.application_fee_bps == 300
    assert platform.get_stripe_secret_key() == "sk_platform"
    assert platform.get_stripe_webhook_secret() == "whsec_platform"


def test_control_platform_credential_change_is_audited_without_secret_values(client):
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_control_old")
    platform.set_stripe_webhook_secret("whsec_control")
    platform.stripe_connect_client_id = "ca_control"
    platform.save()
    superadmin = make_user(
        "platform-control-audit-admin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
        is_staff=True,
    )
    client.force_login(superadmin)

    response = client.post(
        reverse(
            "admin:payments_platformstripeconnectsettings_change",
            args=[platform.pk],
        ),
        {
            "stripe_publishable_key": "",
            "stripe_secret_key": "sk_control_rotated_must_not_leak",
            "stripe_webhook_secret": "",
            "stripe_connect_client_id": "ca_control",
            "application_fee_bps": 0,
            "_save": "Save",
        },
    )

    assert response.status_code == 302
    event = AuditLog.objects.get(
        action="platform.stripe_connect_settings_updated",
        actor=superadmin,
        target_id=str(platform.pk),
    )
    assert "stripe_secret_key" in event.meta["changed_fields"]
    assert "sk_control_rotated_must_not_leak" not in str(event.meta)


def test_control_cannot_delete_platform_connect_settings_singleton(client):
    platform = PlatformStripeConnectSettings.load()
    superadmin = make_user(
        "platform-control-delete-admin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
        is_staff=True,
    )
    client.force_login(superadmin)
    delete_url = reverse(
        "admin:payments_platformstripeconnectsettings_delete",
        args=[platform.pk],
    )

    assert client.get(delete_url).status_code == 403
    assert client.post(delete_url, {"post": "yes"}).status_code == 403
    assert PlatformStripeConnectSettings.objects.filter(pk=platform.pk).exists()


def test_abandoned_connect_session_is_rechecked_before_platform_rotation(
    settings, monkeypatch
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    platform, superadmin = pending_connect_settings("platform-abandoned-session")
    payment = Payment.objects.get(stripe_provider=Payment.StripeProvider.CONNECT)
    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_url="https://checkout.stripe.test/abandoned"
    )
    payment.refresh_from_db()
    checked = []
    monkeypatch.setattr(
        "apps.payments.stripe_client.checkout_session_is_closed",
        lambda source, session_id: checked.append((source, session_id)) or True,
        raising=False,
    )
    client = APIClient()
    client.force_authenticate(superadmin)

    response = client.patch(
        "/api/v1/admin/platform/payment-settings",
        {"stripe_secret_key": "sk_rotated_after_abandonment"},
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200
    assert checked[0][0].provider == Payment.StripeProvider.CONNECT
    assert checked[0][1] == payment.stripe_checkout_session_id
    payment.refresh_from_db()
    platform.refresh_from_db()
    assert payment.stripe_checkout_session_expired_at is not None
    assert payment.stripe_checkout_session_id is None
    assert payment.stripe_checkout_url == ""
    assert platform.get_stripe_secret_key() == "sk_rotated_after_abandonment"
