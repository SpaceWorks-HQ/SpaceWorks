from types import SimpleNamespace

import pytest
from django.contrib import admin
from rest_framework.test import APIClient

from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import MakerspacePaymentSettings
from apps.payments.models import Payment
from decimal import Decimal
from tests.payments.test_machine_payments import service_request
from apps.accounts.models import User
from tests.return_helpers import make_member, make_space, make_user


pytestmark = pytest.mark.django_db


def test_space_manager_updates_raw_credentials_without_secret_leakage():
    makerspace = make_space("payment-settings-api")
    manager = make_member(
        "payment-settings-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    client = APIClient()
    client.force_authenticate(manager)
    url = f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings"

    saved = client.patch(
        url,
        {
            "stripe_publishable_key": "pk_test_client_safe",
            "stripe_secret_key": "sk_test_private",
            "stripe_webhook_secret": "whsec_private",
            "default_currency": "INR",
        },
        format="json",
    )

    assert saved.status_code == 200
    assert saved.data["stripe_secret_key_set"] is True
    assert saved.data["stripe_webhook_secret_set"] is True
    assert saved.data["stripe_publishable_key_set"] is True
    assert saved.data["default_currency"] == "inr"
    assert saved.data["effective_mode"] == "raw"
    assert saved.data["connect_status"] == "unconnected"
    assert "stripe_secret_key" not in saved.data
    assert "stripe_webhook_secret" not in saved.data
    assert "stripe_publishable_key" not in saved.data
    stored = MakerspacePaymentSettings.objects.get(makerspace=makerspace)
    assert stored.stripe_publishable_key == "pk_test_client_safe"
    assert stored.stripe_secret_key != "sk_test_private"
    assert stored.get_stripe_secret_key() == "sk_test_private"

    bootstrap = APIClient().get(f"/api/v1/bootstrap?slug={makerspace.slug}")
    assert bootstrap.status_code == 200
    assert "stripe_publishable_key" not in str(bootstrap.data)

    preserved = client.patch(url, {"default_currency": "usd"}, format="json")
    assert preserved.status_code == 200
    stored.refresh_from_db()
    assert stored.get_stripe_secret_key() == "sk_test_private"
    assert stored.stripe_publishable_key == "pk_test_client_safe"

    cleared = client.patch(
        url,
        {
            "stripe_publishable_key": "",
            "stripe_secret_key": "",
            "stripe_webhook_secret": "",
        },
        format="json",
    )
    assert cleared.status_code == 200
    assert cleared.data["stripe_secret_key_set"] is False
    assert cleared.data["stripe_webhook_secret_set"] is False
    assert cleared.data["stripe_publishable_key_set"] is False


def test_effective_payment_source_resolution_matrix(settings):
    from apps.payments.models import PlatformStripeConnectSettings
    from apps.payments.resolution import resolve_payment_source, source_for_payment

    makerspace = make_space("payment-resolution")
    merchant = MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_resolution",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
        connect_payouts_enabled=True,
    )
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()

    settings.PLATFORM_DOMAIN_SUFFIX = ""
    assert resolve_payment_source(makerspace) is None

    merchant.set_stripe_secret_key("sk_raw")
    merchant.set_stripe_webhook_secret("whsec_raw")
    merchant.stripe_publishable_key = "pk_raw"
    merchant.save()
    raw = resolve_payment_source(makerspace)
    assert raw.provider == "raw"
    assert raw.secret_key == "sk_raw"
    assert raw.publishable_key == "pk_raw"
    raw_payment = SimpleNamespace(
        StripeProvider=Payment.StripeProvider,
        Provider=Payment.Provider,
        provider=Payment.Provider.STRIPE,
        stripe_provider=Payment.StripeProvider.RAW,
        makerspace=makerspace,
    )
    assert source_for_payment(raw_payment).publishable_key == "pk_raw"

    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    assert resolve_payment_source(makerspace).provider == "raw"

    merchant.set_stripe_secret_key("")
    merchant.set_stripe_webhook_secret("")
    merchant.save()
    platform.stripe_publishable_key = "pk_platform"
    platform.save()
    connected = resolve_payment_source(makerspace)
    assert connected.provider == "connect"
    assert connected.secret_key == "sk_platform"
    assert connected.publishable_key == "pk_platform"
    assert connected.connected_account_id == "acct_resolution"
    connect_payment = SimpleNamespace(
        StripeProvider=Payment.StripeProvider,
        Provider=Payment.Provider,
        provider=Payment.Provider.STRIPE,
        stripe_provider=Payment.StripeProvider.CONNECT,
        makerspace=makerspace,
        stripe_connected_account_id="acct_resolution",
    )
    assert source_for_payment(connect_payment).publishable_key == "pk_platform"

    merchant.connect_charges_enabled = False
    merchant.save(update_fields=["connect_charges_enabled", "connect_status_updated_at"])
    assert resolve_payment_source(makerspace) is None


def test_superadmin_updates_platform_connect_settings_without_secret_leakage(settings):
    from apps.payments.models import PlatformStripeConnectSettings

    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    superadmin = make_user(
        "platform-payments-admin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
        is_staff=True,
    )
    ordinary = make_user(
        "platform-payments-denied", access_status=User.AccessStatus.ACTIVE
    )
    url = "/api/v1/admin/platform/payment-settings"

    denied = APIClient()
    denied.force_authenticate(ordinary)
    assert denied.get(url, HTTP_HOST="localhost").status_code == 403

    client = APIClient()
    client.force_authenticate(superadmin)
    response = client.patch(
        url,
        {
            "stripe_publishable_key": "pk_platform_client_safe",
            "stripe_secret_key": "sk_platform_private",
            "stripe_webhook_secret": "whsec_platform_private",
            "stripe_connect_client_id": "ca_public",
            "application_fee_bps": 125,
        },
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200
    assert response.data["stripe_secret_key_set"] is True
    assert response.data["stripe_webhook_secret_set"] is True
    assert response.data["stripe_publishable_key_set"] is True
    assert response.data["stripe_connect_client_id"] == "ca_public"
    assert response.data["application_fee_bps"] == 125
    assert "stripe_secret_key" not in response.data
    assert "stripe_webhook_secret" not in response.data
    assert "stripe_publishable_key" not in response.data
    stored = PlatformStripeConnectSettings.load()
    assert stored.stripe_publishable_key == "pk_platform_client_safe"
    assert stored.stripe_secret_key != "sk_platform_private"
    assert stored.get_stripe_secret_key() == "sk_platform_private"
    assert stored.stripe_secret_key_set is True
    assert stored.stripe_webhook_secret_set is True

    preserved = client.patch(
        url,
        {"application_fee_bps": 150},
        format="json",
        HTTP_HOST="localhost",
    )
    assert preserved.status_code == 200
    stored.refresh_from_db()
    assert stored.stripe_publishable_key == "pk_platform_client_safe"

    cleared = client.patch(
        url,
        {"stripe_publishable_key": ""},
        format="json",
        HTTP_HOST="localhost",
    )
    assert cleared.status_code == 200
    assert cleared.data["stripe_publishable_key_set"] is False
    stored.refresh_from_db()
    assert stored.is_configured is True


def test_webhook_secret_change_is_blocked_while_provider_session_is_pending(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    makerspace = make_space("payment-secret-rotation")
    manager = make_member("payment-secret-rotation-manager", makerspace)
    merchant = MakerspacePaymentSettings(makerspace=makerspace)
    merchant.set_stripe_secret_key("sk_raw")
    merchant.set_stripe_webhook_secret("whsec_raw")
    merchant.save()
    subject = service_request(makerspace, manager)
    payment = Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=subject.id,
        member=manager,
        amount=Decimal("2.00"),
        currency="usd",
        created_by=manager,
        stripe_provider=Payment.StripeProvider.RAW,
    )
    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_session_id="cs_pending_rotation"
    )
    client = APIClient()
    client.force_authenticate(manager)

    response = client.patch(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings",
        {"stripe_webhook_secret": ""},
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 400
    assert "pending" in str(response.data["stripe_webhook_secret"]).lower()
    merchant.refresh_from_db()
    assert merchant.get_stripe_webhook_secret() == "whsec_raw"


def test_platform_connect_admin_form_is_write_only_and_global():
    from apps.payments.models import PlatformStripeConnectSettings
    from config.admin_access import GLOBAL_ADMIN_MODELS

    platform = PlatformStripeConnectSettings.load()
    platform.stripe_publishable_key = "pk_admin_client_safe"
    platform.set_stripe_secret_key("sk_admin_private")
    platform.set_stripe_webhook_secret("whsec_admin_private")
    platform.stripe_connect_client_id = "ca_admin"
    platform.save()

    model_admin = admin.site._registry[PlatformStripeConnectSettings]
    rendered = model_admin.form(instance=platform).as_p()

    assert "sk_admin_private" not in rendered
    assert "whsec_admin_private" not in rendered
    assert "pk_admin_client_safe" not in rendered
    assert "payments.platformstripeconnectsettings" in GLOBAL_ADMIN_MODELS
