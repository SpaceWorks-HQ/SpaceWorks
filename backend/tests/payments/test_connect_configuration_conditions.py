"""Connect availability can be tested without calling Stripe or owning a paid account."""

import pytest

from apps.accounts.models import User
from apps.payments.models import StripeConnectOAuthState
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def test_self_host_platform_settings_and_onboarding_return_404(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    space = make_space("connect-self-host-unavailable")
    root = make_user("connect-self-host-root", role=User.Role.SUPERADMIN, is_superuser=True)
    client = authenticated_client(root)
    assert client.get("/api/v1/admin/platform/payment-settings").status_code == 404
    assert client.post(f"/api/v1/admin/makerspace/{space.pk}/payment-settings/connect/onboard").status_code == 404
    assert not StripeConnectOAuthState.objects.exists()


def test_unconfigured_managed_onboarding_returns_503_without_minting_state(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.example"
    # Managed host admission refuses unknown hosts; the test client is an infra host.
    settings.INFRA_HOSTS = {"testserver"}
    settings.STRIPE_CONNECT_REDIRECT_URI = "https://app.example/callback"
    space = make_space("connect-unconfigured")
    manager = make_member("connect-unconfigured-manager", space)
    # Managed host admission reads the raw Host header, which the test client omits.
    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{space.pk}/payment-settings/connect/onboard",
        HTTP_HOST="testserver",
    )
    assert response.status_code == 503
    assert response.data == {"detail": "Stripe Connect is unavailable."}
    assert not StripeConnectOAuthState.objects.exists()
