from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.payments import stripe_client
from apps.payments.availability import online_payments_enabled
from apps.payments.models import MakerspacePaymentSettings
from tests.return_helpers import make_space


pytestmark = pytest.mark.django_db


class _FakeSignatureError(Exception):
    """Module-level so a nested fake-stripe class body can reference it (a class body
    cannot see an enclosing function's locals)."""


def configured_settings(makerspace):
    settings = MakerspacePaymentSettings(makerspace=makerspace)
    settings.set_stripe_secret_key("sk_test_secret")
    settings.set_stripe_webhook_secret("whsec_test_secret")
    settings.save()
    return settings


def test_payment_credentials_are_encrypted_and_round_trip():
    makerspace = make_space("payment-creds")
    settings = configured_settings(makerspace)

    settings.refresh_from_db()

    assert settings.stripe_secret_key != "sk_test_secret"
    assert settings.stripe_webhook_secret != "whsec_test_secret"
    assert settings.get_stripe_secret_key() == "sk_test_secret"
    assert settings.get_stripe_webhook_secret() == "whsec_test_secret"


def test_is_configured_requires_both_payment_secrets():
    makerspace = make_space("payment-configured")
    settings = MakerspacePaymentSettings(makerspace=makerspace)

    assert settings.is_configured is False
    settings.stripe_publishable_key = "pk_test_client_safe"
    assert settings.is_configured is False
    settings.set_stripe_secret_key("sk_test_secret")
    assert settings.is_configured is False
    settings.set_stripe_webhook_secret("whsec_test_secret")
    assert settings.is_configured is True
    assert settings.stripe_publishable_key == "pk_test_client_safe"


def test_default_currency_is_lowercased_and_validated():
    makerspace = make_space("payment-currency")
    settings = MakerspacePaymentSettings(makerspace=makerspace, default_currency="USD")
    settings.save()
    assert settings.default_currency == "usd"

    with pytest.raises(ValidationError):
        MakerspacePaymentSettings(makerspace=make_space("payment-bad-currency"), default_currency="US").save()


def test_online_payments_requires_feature_and_configuration():
    makerspace = make_space("payment-availability")

    def features(*keys):
        makerspace.enabled_features = list(keys)
        makerspace.save(update_fields=["enabled_features", "updated_at"])

    assert online_payments_enabled(makerspace, "machines") is False
    features("payments.enabled", "payments.machines")
    # Features on, credentials absent.
    assert online_payments_enabled(makerspace, "machines") is False

    configured_settings(makerspace)
    assert online_payments_enabled(makerspace, "machines") is True

    # The A6 master switch is an additive AND: dropping it turns everything off even
    # with the domain feature on and credentials configured.
    features("payments.machines")
    assert online_payments_enabled(makerspace, "machines") is False

    features()
    assert online_payments_enabled(makerspace, "machines") is False


def test_per_request_client_never_mutates_stripe_global_api_key(monkeypatch):
    class FakeStripe:
        api_key = "process-global-key"

        class StripeClient:
            def __init__(self, *, api_key):
                self.api_key = api_key

    makerspace = make_space("payment-client")
    settings = configured_settings(makerspace)
    monkeypatch.setattr(stripe_client, "_stripe_module", lambda: FakeStripe)

    first = stripe_client.build_client(settings)
    second = stripe_client.build_client(settings)

    assert first is not second
    assert first.api_key == "sk_test_secret"
    assert FakeStripe.api_key == "process-global-key"


def test_webhook_valid_signature_is_safely_acknowledged_without_state_change(monkeypatch):
    makerspace = make_space("payment-webhook-ok")
    configured_settings(makerspace)
    construct_event = Mock(return_value={"id": "evt_123", "type": "checkout.session.completed"})
    monkeypatch.setattr("apps.payments.views.construct_event", construct_event)
    before_audit_count = AuditLog.objects.count()

    response = APIClient().generic(
        "POST",
        f"/api/v1/webhooks/stripe/{makerspace.public_code}",
        b'{"id":"evt_123"}',
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=valid",
    )

    assert response.status_code == 200
    assert construct_event.call_args.args[0] == b'{"id":"evt_123"}'
    assert AuditLog.objects.count() == before_audit_count


def test_webhook_rejects_invalid_signature(monkeypatch):
    makerspace = make_space("payment-webhook-invalid")
    configured_settings(makerspace)
    monkeypatch.setattr(
        "apps.payments.views.construct_event",
        Mock(side_effect=stripe_client.StripeWebhookSignatureError("invalid")),
    )

    response = APIClient().post(
        f"/api/v1/webhooks/stripe/{makerspace.public_code}",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="bad",
    )

    assert response.status_code == 400


def test_webhook_rejects_unknown_makerspace():
    """Archived is NO LONGER refused, and that reversal is deliberate.

    This test asserted an archived makerspace 404s too. That was written in C.2 (`92eda37`),
    when the endpoint was **verify-only** -- it settled nothing, so refusing cost nothing.
    Settlement arrived in C.3 and the filter was never revisited, which silently broke the
    documented invariant that a real charge is never stranded: the provider had already taken
    the member's money and the 404 only prevented RECORDING it. Settlement after archival is
    now pinned in `tests/payments/test_archived_space_payments.py`.
    """
    client = APIClient()
    assert client.post("/api/v1/webhooks/stripe/NOPE", b"{}", content_type="application/json").status_code == 404


def test_webhook_rejects_an_unconfigured_makerspace_without_creating_settings():
    makerspace = make_space("payment-webhook-unconfigured")

    response = APIClient().post(
        f"/api/v1/webhooks/stripe/{makerspace.public_code}", b"{}", content_type="application/json"
    )

    assert response.status_code == 400
    assert not MakerspacePaymentSettings.objects.filter(makerspace=makerspace).exists()


def test_payment_settings_admin_masks_secrets_and_is_superuser_only():
    makerspace = make_space("payment-admin")
    settings = configured_settings(makerspace)
    settings.stripe_publishable_key = "pk_admin_client_safe"
    settings.save(update_fields=["stripe_publishable_key"])
    model_admin = admin.site._registry[MakerspacePaymentSettings]
    form = model_admin.form(instance=settings)
    staff = SimpleNamespace(
        is_authenticated=True,
        is_active=True,
        is_superuser=False,
        access_status=User.AccessStatus.ACTIVE,
        must_change_password=False,
    )

    assert "sk_test_secret" not in form.as_p()
    assert "whsec_test_secret" not in form.as_p()
    assert "pk_admin_client_safe" not in form.as_p()
    assert model_admin.has_view_permission(SimpleNamespace(user=staff)) is False
    assert model_admin.list_filter == ("makerspace",)


def test_construct_event_uses_stripe_verification(monkeypatch):
    construct = Mock(return_value={"id": "evt_verified"})

    class FakeStripe:
        class Webhook:
            construct_event = construct

    monkeypatch.setattr(stripe_client, "_stripe_module", lambda: FakeStripe)

    assert stripe_client.construct_event(b"{}", "t=1,v1=good", "whsec_test") == {"id": "evt_verified"}
    construct.assert_called_once_with(b"{}", "t=1,v1=good", "whsec_test")


def test_construct_event_maps_stripe_signature_failures(monkeypatch):
    class FakeStripe:
        class error:
            SignatureVerificationError = _FakeSignatureError

        class Webhook:
            @staticmethod
            def construct_event(*args):
                raise _FakeSignatureError("bad signature")

    monkeypatch.setattr(stripe_client, "_stripe_module", lambda: FakeStripe)

    with pytest.raises(stripe_client.StripeWebhookSignatureError):
        stripe_client.construct_event(b"{}", "bad", "whsec_test")
