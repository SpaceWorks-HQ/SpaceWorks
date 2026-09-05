from decimal import Decimal
from threading import Event, Thread

import pytest
from django.db import close_old_connections
from rest_framework.test import APIClient

from apps.admin_api import serializers_payments
from apps.accounts.models import User
from apps.payments import credential_validation
from apps.payments.models import (
    MakerspacePaymentSettings,
    Payment,
    PlatformStripeConnectSettings,
)
from apps.payments.services import create_checkout_url
from tests.payments.test_machine_payments import service_request
from tests.return_helpers import make_member, make_space, make_user


pytestmark = pytest.mark.django_db(transaction=True)


def test_raw_rotation_cannot_commit_between_session_check_and_persist(monkeypatch):
    makerspace = make_space("raw-rotation-lock")
    actor = make_member("raw-rotation-lock-manager", makerspace)
    payment_settings = MakerspacePaymentSettings.objects.create(makerspace=makerspace)
    payment_settings.set_stripe_secret_key("sk_old")
    payment_settings.set_stripe_webhook_secret("whsec_old")
    payment_settings.save()
    payment = Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=service_request(makerspace, actor).id,
        member=actor,
        amount=Decimal("2.00"),
        currency="usd",
        created_by=actor,
        stripe_provider=Payment.StripeProvider.RAW,
    )
    checkout_entered = Event()
    release_checkout = Event()
    rotation_entered = Event()
    rotation_finished = Event()
    results = {}

    def create_session(source, **_params):
        results["checkout_secret"] = source.secret_key
        checkout_entered.set()
        assert release_checkout.wait(10)
        return {"id": "cs_rotation_lock", "url": "https://checkout.test/locked"}

    monkeypatch.setattr(
        "apps.payments.services_checkout.stripe_client.create_checkout_session", create_session
    )
    update_settings = serializers_payments.update_payment_settings

    def signaled_update(*args, **kwargs):
        rotation_entered.set()
        return update_settings(*args, **kwargs)

    monkeypatch.setattr(
        serializers_payments, "update_payment_settings", signaled_update
    )

    def checkout_worker():
        close_old_connections()
        try:
            results["checkout_url"] = create_checkout_url(payment.pk)
        finally:
            close_old_connections()

    def rotation_worker():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(type(actor).objects.get(pk=actor.pk))
            response = client.patch(
                f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings",
                {"stripe_secret_key": "sk_new"},
                format="json",
            )
            results["rotation_status"] = response.status_code
            results["rotation_data"] = response.data
        finally:
            rotation_finished.set()
            close_old_connections()

    checkout_thread = Thread(target=checkout_worker)
    rotation_thread = Thread(target=rotation_worker)
    checkout_thread.start()
    assert checkout_entered.wait(10)
    rotation_thread.start()
    assert rotation_entered.wait(10)
    assert not rotation_finished.wait(0.25)
    release_checkout.set()
    checkout_thread.join(10)
    rotation_thread.join(10)

    assert not checkout_thread.is_alive()
    assert not rotation_thread.is_alive()
    assert results["checkout_secret"] == "sk_old"
    assert results["checkout_url"] == "https://checkout.test/locked"
    assert results["rotation_status"] == 400
    assert "pending" in str(results["rotation_data"]["stripe_secret_key"]).lower()
    payment_settings.refresh_from_db()
    assert payment_settings.get_stripe_secret_key() == "sk_old"


def test_connect_checkout_waits_for_platform_credential_commit(settings, monkeypatch):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.PUBLIC_APP_BASE_URL = "https://app.managed.test"
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform_old")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-rotation-lock")
    merchant = MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_rotationlock",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
        connect_payouts_enabled=True,
    )
    member = make_member("connect-rotation-lock-member", makerspace)
    superadmin = make_user(
        "connect-rotation-lock-admin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
        is_staff=True,
    )
    payment = Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=service_request(makerspace, member).id,
        member=member,
        amount=Decimal("2.00"),
        currency="usd",
        created_by=member,
        stripe_provider=Payment.StripeProvider.CONNECT,
        stripe_connected_account_id=merchant.connect_account_id,
    )
    validation_checked = Event()
    release_rotation = Event()
    checkout_entered = Event()
    results = {}
    original_validate = credential_validation.validate_platform_credential_changes

    def paused_validation(*args, **kwargs):
        result = original_validate(*args, **kwargs)
        validation_checked.set()
        assert release_rotation.wait(10)
        return result

    def create_session(source, **_params):
        results["checkout_secret"] = source.secret_key
        checkout_entered.set()
        return {"id": "cs_connect_rotation", "url": "https://checkout.test/connect"}

    monkeypatch.setattr(
        credential_validation,
        "validate_platform_credential_changes",
        paused_validation,
    )
    monkeypatch.setattr(
        "apps.payments.services_checkout.refresh_connected_account", lambda _merchant: merchant
    )
    monkeypatch.setattr(
        "apps.payments.services_checkout.stripe_client.create_checkout_session", create_session
    )

    def rotation_worker():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(type(superadmin).objects.get(pk=superadmin.pk))
            response = client.patch(
                "/api/v1/admin/platform/payment-settings",
                {"stripe_secret_key": "sk_platform_new"},
                format="json",
                HTTP_HOST="localhost",
            )
            results["rotation_status"] = response.status_code
        finally:
            close_old_connections()

    def checkout_worker():
        close_old_connections()
        try:
            results["checkout_url"] = create_checkout_url(payment.pk)
        finally:
            close_old_connections()

    rotation_thread = Thread(target=rotation_worker)
    checkout_thread = Thread(target=checkout_worker)
    rotation_thread.start()
    assert validation_checked.wait(10)
    checkout_thread.start()
    assert not checkout_entered.wait(0.25)
    release_rotation.set()
    rotation_thread.join(10)
    checkout_thread.join(10)

    assert not rotation_thread.is_alive()
    assert not checkout_thread.is_alive()
    assert results["rotation_status"] == 200
    assert results["checkout_secret"] == "sk_platform_new"
    assert results["checkout_url"] == "https://checkout.test/connect"
