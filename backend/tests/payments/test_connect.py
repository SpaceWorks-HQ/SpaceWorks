import hashlib
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from rest_framework.test import APIClient
from unittest.mock import Mock

from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import (
    MakerspacePaymentSettings,
    Payment,
    PlatformStripeConnectSettings,
    StripeConnectOAuthState,
)
from apps.payments.services import create_checkout_url, create_payment
from apps.payments.stripe_client import PaymentsUnavailable
from tests.payments.test_machine_payments import service_request
from tests.return_helpers import make_member, make_space


pytestmark = pytest.mark.django_db


def test_create_payment_fails_closed_when_no_payment_source_resolves(monkeypatch):
    makerspace = make_space("connect-source-disappeared")
    actor = make_member("connect-source-disappeared-member", makerspace)
    subject = service_request(makerspace, actor)
    monkeypatch.setattr(
        "apps.payments.services.resolve_payment_source",
        lambda _makerspace: None,
    )

    with pytest.raises(PaymentsUnavailable):
        create_payment(
            makerspace=makerspace,
            subject_type="machine_service_request",
            subject_id=subject.id,
            member=actor,
            amount=Decimal("10.00"),
            currency="usd",
            created_by=actor,
        )

    assert not Payment.objects.filter(
        subject_type="machine_service_request", subject_id=subject.id
    ).exists()


def test_oauth_exchange_uses_the_installed_stripe_client_surface(monkeypatch):
    from apps.payments import connect

    calls = []

    class OAuth:
        def token(self, *, params):
            calls.append(params)
            return {"stripe_user_id": "acct_oauth_surface"}

    client = type("Client", (), {"oauth": OAuth()})()
    monkeypatch.setattr(connect, "_platform_client", lambda: client)

    assert connect.exchange_oauth_code("ac_test") == "acct_oauth_surface"
    assert calls == [{"grant_type": "authorization_code", "code": "ac_test"}]


def test_connect_onboarding_uses_fixed_redirect_and_stores_only_hashed_state(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.STRIPE_CONNECT_REDIRECT_URI = (
        "https://api.managed.test/api/v1/payments/connect/callback"
    )
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-onboard")
    manager = make_member(
        "connect-onboard-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    client = APIClient()
    client.force_authenticate(manager)

    response = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings/connect/onboard",
        {"return_url": "https://evil.test/steal"},
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200
    query = parse_qs(urlparse(response.data["authorize_url"]).query)
    assert query["client_id"] == ["ca_platform"]
    assert query["redirect_uri"] == [settings.STRIPE_CONNECT_REDIRECT_URI]
    assert query["scope"] == ["read_write"]
    assert "evil.test" not in response.data["authorize_url"]
    raw_state = query["state"][0]
    stored = StripeConnectOAuthState.objects.get(makerspace=makerspace)
    assert stored.initiated_by == manager
    assert stored.state_digest == hashlib.sha256(raw_state.encode()).hexdigest()
    assert raw_state not in stored.state_digest


def test_connect_callback_consumes_state_stores_account_and_rejects_replay(
    settings, monkeypatch
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.PUBLIC_APP_BASE_URL = "https://app.managed.test"
    settings.STRIPE_CONNECT_REDIRECT_URI = (
        "https://api.managed.test/api/v1/payments/connect/callback"
    )
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-callback")
    manager = make_member(
        "connect-callback-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    client = APIClient()
    client.force_authenticate(manager)
    started = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings/connect/onboard",
        format="json",
        HTTP_HOST="localhost",
    )
    raw_state = parse_qs(urlparse(started.data["authorize_url"]).query)["state"][0]
    monkeypatch.setattr(
        "apps.payments.views_connect.exchange_oauth_code",
        lambda code: "acct_callback",
    )
    fetches = []

    def fetch_mapped_account(account_id):
        mapped = MakerspacePaymentSettings.objects.get(makerspace=makerspace)
        assert mapped.connect_account_id == account_id
        if not fetches:
            assert mapped.connect_status == MakerspacePaymentSettings.ConnectStatus.PENDING
            assert mapped.connect_charges_enabled is False
        fetches.append(account_id)
        return {
            "id": account_id,
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
        }

    monkeypatch.setattr(
        "apps.payments.views_connect.fetch_account",
        fetch_mapped_account,
    )

    callback = APIClient().get(
        "/api/v1/payments/connect/callback",
        {"state": raw_state, "code": "ac_callback"},
        HTTP_HOST="localhost",
    )

    assert callback.status_code == 302
    assert callback["Location"] == (
        "https://app.managed.test/m/connect-callback/admin/settings"
        "?stripe_connect=success"
    )
    assert callback["Referrer-Policy"] == "no-referrer"
    stored_state = StripeConnectOAuthState.objects.get(makerspace=makerspace)
    assert stored_state.consumed_at is not None
    merchant = MakerspacePaymentSettings.objects.get(makerspace=makerspace)
    assert merchant.connect_account_id == "acct_callback"
    assert merchant.connect_status == MakerspacePaymentSettings.ConnectStatus.ACTIVE

    replay = APIClient().get(
        "/api/v1/payments/connect/callback",
        {"state": raw_state, "code": "ac_replay"},
        HTTP_HOST="localhost",
    )
    assert replay.status_code == 302
    assert replay["Location"] == (
        "https://app.managed.test/admin/settings?stripe_connect=failed"
    )
    assert makerspace.slug not in replay["Location"]

    first_assignment = merchant.connect_account_assigned_at
    restarted = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings/connect/onboard",
        format="json",
        HTTP_HOST="localhost",
    )
    restarted_state = parse_qs(
        urlparse(restarted.data["authorize_url"]).query
    )["state"][0]
    reconnected = APIClient().get(
        "/api/v1/payments/connect/callback",
        {"state": restarted_state, "code": "ac_same_account"},
        HTTP_HOST="localhost",
    )

    merchant.refresh_from_db()
    assert reconnected["Location"].endswith("stripe_connect=success")
    assert merchant.connect_account_id == "acct_callback"
    assert merchant.connect_account_assigned_at > first_assignment


def test_connect_callback_replacement_revokes_previous_account(settings, monkeypatch):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.PUBLIC_APP_BASE_URL = "https://app.managed.test"
    settings.STRIPE_CONNECT_REDIRECT_URI = (
        "https://api.managed.test/api/v1/payments/connect/callback"
    )
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-replacement-revoke")
    manager = make_member(
        "connect-replacement-revoke-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_previous",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
    )
    client = APIClient()
    client.force_authenticate(manager)
    started = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings/connect/onboard",
        HTTP_HOST="localhost",
    )
    raw_state = parse_qs(urlparse(started.data["authorize_url"]).query)["state"][0]
    monkeypatch.setattr(
        "apps.payments.views_connect.exchange_oauth_code", lambda _code: "acct_new"
    )
    monkeypatch.setattr(
        "apps.payments.views_connect.fetch_account",
        lambda account_id: {
            "id": account_id,
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
        },
    )
    revoked = []
    monkeypatch.setattr(
        "apps.payments.views_connect.deauthorize_account", revoked.append
    )

    response = APIClient().get(
        "/api/v1/payments/connect/callback",
        {"state": raw_state, "code": "ac_new"},
        HTTP_HOST="localhost",
    )

    merchant = MakerspacePaymentSettings.objects.get(makerspace=makerspace)
    assert response["Location"].endswith("stripe_connect=success")
    assert merchant.connect_account_id == "acct_new"
    assert revoked == ["acct_previous"]


def test_older_oauth_callback_cannot_overwrite_newer_onboarding(settings, monkeypatch):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.PUBLIC_APP_BASE_URL = "https://app.managed.test"
    settings.STRIPE_CONNECT_REDIRECT_URI = (
        "https://api.managed.test/api/v1/payments/connect/callback"
    )
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-superseded")
    manager = make_member(
        "connect-superseded-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    client = APIClient()
    client.force_authenticate(manager)

    first = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings/connect/onboard",
        format="json",
        HTTP_HOST="localhost",
    )
    second = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings/connect/onboard",
        format="json",
        HTTP_HOST="localhost",
    )
    first_state = parse_qs(urlparse(first.data["authorize_url"]).query)["state"][0]
    second_state = parse_qs(urlparse(second.data["authorize_url"]).query)["state"][0]
    exchanged = []
    monkeypatch.setattr(
        "apps.payments.views_connect.exchange_oauth_code",
        lambda code: exchanged.append(code) or f"acct_{code}",
    )
    monkeypatch.setattr(
        "apps.payments.views_connect.fetch_account",
        lambda account_id: {
            "id": account_id,
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
        },
    )

    newer = APIClient().get(
        "/api/v1/payments/connect/callback",
        {"state": second_state, "code": "newer"},
        HTTP_HOST="localhost",
    )
    older = APIClient().get(
        "/api/v1/payments/connect/callback",
        {"state": first_state, "code": "older"},
        HTTP_HOST="localhost",
    )

    merchant = MakerspacePaymentSettings.objects.get(makerspace=makerspace)
    assert newer["Location"].endswith("stripe_connect=success")
    assert older["Location"].endswith("stripe_connect=failed")
    assert merchant.connect_account_id == "acct_newer"
    assert exchanged == ["newer"]


def test_connect_checkout_uses_direct_charge_and_snapshots_fee(settings, monkeypatch):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.PUBLIC_APP_BASE_URL = "https://app.managed.test"
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.application_fee_bps = 125
    platform.save()
    makerspace = make_space("connect-checkout")
    merchant = MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_checkout",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
        connect_payouts_enabled=True,
    )
    actor = make_member("connect-checkout-member", makerspace)
    subject = service_request(makerspace, actor)
    payment = create_payment(
        makerspace=makerspace,
        subject_type="machine_service_request",
        subject_id=subject.id,
        member=actor,
        amount=Decimal("10.01"),
        currency="usd",
        created_by=actor,
    )
    monkeypatch.setattr(
        "apps.payments.services.refresh_connected_account",
        lambda _merchant: merchant,
    )
    calls = []

    class Sessions:
        def create(self, *, params, options=None):
            calls.append((params, options))
            return {"id": "cs_connect", "url": "https://checkout.stripe.test/connect"}

    class FakeStripe:
        api_key = "unchanged-global"

        class StripeClient:
            def __init__(self, *, api_key):
                assert api_key == "sk_platform"
                self.v1 = type(
                    "V1", (), {"checkout": type("Checkout", (), {"sessions": Sessions()})()}
                )()

    monkeypatch.setattr("apps.payments.stripe_client._stripe_module", lambda: FakeStripe)

    assert create_checkout_url(payment.id) == "https://checkout.stripe.test/connect"
    payment.refresh_from_db()
    assert payment.stripe_provider == "connect"
    assert payment.stripe_connected_account_id == "acct_checkout"
    assert payment.stripe_application_fee_amount == 13
    params, options = calls[0]
    assert options == {
        "stripe_account": "acct_checkout",
        "idempotency_key": f"payment-checkout-{payment.id}-0",
    }
    assert params["payment_intent_data"]["application_fee_amount"] == 13
    assert FakeStripe.api_key == "unchanged-global"


def test_connect_checkout_persists_restricted_account_refresh(settings, monkeypatch):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-checkout-restricted")
    merchant = MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_restricted",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
        connect_payouts_enabled=True,
    )
    actor = make_member("connect-checkout-restricted-member", makerspace)
    payment = create_payment(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=service_request(makerspace, actor).id,
        member=actor,
        amount=Decimal("10.00"),
        currency="usd",
        created_by=actor,
    )
    monkeypatch.setattr(
        "apps.payments.connect.fetch_account",
        lambda _account_id: {
            "charges_enabled": False,
            "payouts_enabled": False,
            "details_submitted": True,
        },
    )

    with pytest.raises(PaymentsUnavailable):
        create_checkout_url(payment.id)

    merchant.refresh_from_db()
    assert merchant.connect_status == MakerspacePaymentSettings.ConnectStatus.RESTRICTED
    assert merchant.connect_charges_enabled is False
    assert merchant.connect_payouts_enabled is False


def test_raw_payment_fails_closed_after_provider_switch_to_connect(
    settings, monkeypatch
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.PUBLIC_APP_BASE_URL = "https://app.managed.test"
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("raw-snapshot-provider-switch")
    merchant = MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_rawswitch",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
        connect_payouts_enabled=True,
    )
    merchant.set_stripe_secret_key("sk_raw")
    merchant.set_stripe_webhook_secret("whsec_raw")
    merchant.save()
    actor = make_member("raw-snapshot-provider-switch-member", makerspace)
    payment = create_payment(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=service_request(makerspace, actor).id,
        member=actor,
        amount=Decimal("10.00"),
        currency="usd",
        created_by=actor,
    )
    assert payment.stripe_provider == Payment.StripeProvider.RAW

    merchant.set_stripe_secret_key("")
    merchant.set_stripe_webhook_secret("")
    merchant.save()
    checkout_calls = []
    expiry_calls = []
    monkeypatch.setattr(
        "apps.payments.services.stripe_client.create_checkout_session",
        lambda source, **params: checkout_calls.append((source, params)),
    )
    monkeypatch.setattr(
        "apps.payments.services.stripe_client.expire_checkout_session",
        lambda source, session_id: expiry_calls.append((source, session_id)),
    )
    client = APIClient()
    client.force_authenticate(actor)

    checkout = client.post(
        f"/api/v1/member/makerspaces/{makerspace.pk}/payments/{payment.pk}/checkout",
        HTTP_HOST="localhost",
    )

    assert checkout.status_code == 503
    assert checkout.data["code"] == "payments_unavailable"
    assert checkout_calls == []

    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_session_id="cs_raw_snapshot"
    )
    reconciled = client.post(
        f"/api/v1/admin/machine-service/payments/{payment.pk}/mark-offline",
        HTTP_HOST="localhost",
    )

    assert reconciled.status_code == 200
    assert reconciled.data["status"] == Payment.Status.PAID_OFFLINE
    assert expiry_calls == []


def test_connect_payment_keeps_snapshot_after_provider_switch_to_raw(
    settings, monkeypatch
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.PUBLIC_APP_BASE_URL = "https://app.managed.test"
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-snapshot-provider-switch")
    merchant = MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_connectswitch",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
        connect_payouts_enabled=True,
    )
    actor = make_member("connect-snapshot-provider-switch-member", makerspace)
    payment = create_payment(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=service_request(makerspace, actor).id,
        member=actor,
        amount=Decimal("10.00"),
        currency="usd",
        created_by=actor,
    )
    assert payment.stripe_provider == Payment.StripeProvider.CONNECT
    assert payment.stripe_connected_account_id == "acct_connectswitch"

    merchant.set_stripe_secret_key("sk_raw")
    merchant.set_stripe_webhook_secret("whsec_raw")
    merchant.save()
    monkeypatch.setattr(
        "apps.payments.services.refresh_connected_account", lambda _merchant: merchant
    )
    checkout_sources = []
    expiry_sources = []

    def create_session(source, **_params):
        checkout_sources.append(source)
        return {
            "id": "cs_connect_snapshot",
            "url": "https://checkout.stripe.test/connect-snapshot",
        }

    monkeypatch.setattr(
        "apps.payments.services.stripe_client.create_checkout_session", create_session
    )
    monkeypatch.setattr(
        "apps.payments.services.stripe_client.expire_checkout_session",
        lambda source, _session_id: expiry_sources.append(source),
    )
    client = APIClient()
    client.force_authenticate(actor)

    checkout = client.post(
        f"/api/v1/member/makerspaces/{makerspace.pk}/payments/{payment.pk}/checkout",
        HTTP_HOST="localhost",
    )
    reconciled = client.post(
        f"/api/v1/admin/machine-service/payments/{payment.pk}/mark-offline",
        HTTP_HOST="localhost",
    )

    assert checkout.status_code == 200
    assert reconciled.status_code == 200
    assert checkout_sources[0].provider == Payment.StripeProvider.CONNECT
    assert checkout_sources[0].connected_account_id == "acct_connectswitch"
    assert expiry_sources[0].provider == Payment.StripeProvider.CONNECT
    assert expiry_sources[0].connected_account_id == "acct_connectswitch"


def test_connect_webhook_verifies_platform_secret_and_routes_snapshot(
    settings, monkeypatch
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-webhook")
    merchant = MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_webhook",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
    )
    actor = make_member("connect-webhook-member", makerspace)
    subject = service_request(makerspace, actor)
    payment = create_payment(
        makerspace=makerspace,
        subject_type="machine_service_request",
        subject_id=subject.id,
        member=actor,
        amount=Decimal("4.00"),
        currency="usd",
        created_by=actor,
    )
    type(payment).objects.filter(pk=payment.pk).update(
        stripe_checkout_session_id="cs_connect_webhook"
    )
    event = {
        "id": "evt_connect_webhook",
        "account": "acct_webhook",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_connect_webhook",
                "payment_status": "paid",
                "payment_intent": "pi_connect_webhook",
            }
        },
    }
    construct = Mock(return_value=event)
    monkeypatch.setattr("apps.payments.views_connect.construct_event", construct)

    response = APIClient().generic(
        "POST",
        "/api/v1/webhooks/stripe/connect",
        b'{"id":"evt_connect_webhook"}',
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=valid",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200
    construct.assert_called_once_with(
        b'{"id":"evt_connect_webhook"}', "t=1,v1=valid", "whsec_platform"
    )
    payment.refresh_from_db()
    assert payment.status == payment.Status.PAID_ONLINE

    repeated = APIClient().generic(
        "POST",
        "/api/v1/webhooks/stripe/connect",
        b'{"id":"evt_connect_webhook"}',
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=valid",
        HTTP_HOST="localhost",
    )
    assert repeated.status_code == 200


def test_connect_expired_webhook_confirms_checkout_session_is_closed(
    settings, monkeypatch
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_platform")
    platform.set_stripe_webhook_secret("whsec_platform")
    platform.stripe_connect_client_id = "ca_platform"
    platform.save()
    makerspace = make_space("connect-expired-webhook")
    merchant = MakerspacePaymentSettings.objects.create(
        makerspace=makerspace,
        connect_account_id="acct_expiredwebhook",
        connect_status=MakerspacePaymentSettings.ConnectStatus.ACTIVE,
        connect_charges_enabled=True,
    )
    actor = make_member("connect-expired-webhook-member", makerspace)
    payment = create_payment(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=service_request(makerspace, actor).id,
        member=actor,
        amount=Decimal("4.00"),
        currency="usd",
        created_by=actor,
    )
    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_session_id="cs_connect_expired",
        stripe_checkout_url="https://checkout.stripe.test/expired",
    )
    event = {
        "id": "evt_connect_expired",
        "account": "acct_expiredwebhook",
        "type": "checkout.session.expired",
        "data": {"object": {"id": "cs_connect_expired"}},
    }
    monkeypatch.setattr(
        "apps.payments.views_connect.construct_event", Mock(return_value=event)
    )

    response = APIClient().generic(
        "POST",
        "/api/v1/webhooks/stripe/connect",
        b'{"id":"evt_connect_expired"}',
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=valid",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
    assert payment.stripe_checkout_session_expired_at is not None
    assert payment.stripe_checkout_session_id is None
    assert payment.stripe_checkout_url == ""

    created = []
    monkeypatch.setattr(
        "apps.payments.services.member_payment_return_url",
        lambda _makerspace: "https://space.example/member",
    )
    monkeypatch.setattr(
        "apps.payments.services.refresh_connected_account",
        lambda _merchant: merchant,
    )
    monkeypatch.setattr(
        "apps.payments.services.stripe_client.create_checkout_session",
        lambda _source, **params: created.append(params)
        or {
            "id": "cs_connect_replacement",
            "url": "https://checkout.stripe.test/replacement",
        },
    )

    assert create_checkout_url(payment.id) == "https://checkout.stripe.test/replacement"
    payment.refresh_from_db()
    assert created[0]["idempotency_key"] != f"payment-checkout-{payment.id}-0"
    assert payment.stripe_checkout_session_expired_at is None
    assert payment.stripe_checkout_session_id == "cs_connect_replacement"
