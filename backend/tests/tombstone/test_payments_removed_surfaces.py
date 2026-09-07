"""apps/payments_rail under the tombstone profile.

A deployment that takes no money online ships no provider surfaces: checkout, the native
payment sheet, Connect, refunds and every webhook.

The contract INVERTED when the rail was split out of the ledger. It used to be that
tombstoning `payments` removed the reconciliation console and the member's payment
history too -- which, once money owed could be recorded without any gateway, meant such a
deployment accrued debts nobody could read or settle. The ledger is permanently core now,
so this file asserts both halves: the rail is gone, and the ledger is emphatically not.

The most important assertion is still the webhook one: an endpoint that accepted and
verified a Stripe event on a deployment shipping no provider code would settle money
through a rail that is not there.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.payments.models import (
    MakerspacePaymentSettings,
    Payment,
    PlatformStripeConnectSettings,
)
from apps.separability.registry import runtime_active
from apps.separability.tombstones import unavailable_apps
from config.unfold import UNFOLD

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# The rail: gone.
# --------------------------------------------------------------------------

def test_the_rail_is_registered_as_inactive_and_the_ledger_is_not():
    assert runtime_active("payments_rail") is False
    # The ledger app is not separable at all, so it never registers a tombstone and
    # `runtime_active` answers True for it.
    assert runtime_active("payments") is True


def test_the_legacy_payments_label_still_tombstones_the_rail():
    """`TOMBSTONED_APPS=payments` is what existing deployments have written down.

    It must keep meaning "ship no online payments" rather than failing startup with
    separability.E007 on upgrade -- this whole profile runs under that spelling.
    """
    assert "payments_rail" in unavailable_apps()
    assert "payments" not in unavailable_apps()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/webhooks/stripe/connect",
        "/api/v1/webhooks/stripe/abc123",
        "/api/v1/payments/connect/callback",
        "/api/v1/admin/makerspace/1/payments/2/refund",
        "/api/v1/member/makerspaces/1/payments/2/checkout",
        "/api/v1/member/makerspaces/1/payments/2/mobile-intent",
    ],
)
def test_no_rail_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_stripe_webhook_does_not_answer():
    """The one that matters: no provider code is shipped to settle against."""
    response = APIClient().post("/api/v1/webhooks/stripe/abc123", {}, format="json")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/platform/payment-settings",
        "/api/v1/admin/makerspace/1/payment-settings",
    ],
)
def test_no_credential_route_resolves(path):
    # These live in `admin_api`'s urlconf rather than the app's own, so they need the
    # in-place `_separable` gate instead of a dropped include().
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_admin_does_not_register_the_credential_models():
    assert MakerspacePaymentSettings not in admin.site._registry
    assert PlatformStripeConnectSettings not in admin.site._registry


def test_the_sidebar_offers_no_payment_entry():
    """A leftover entry raises NoReverseMatch and 500s the whole console."""
    titles = [
        str(item["title"])
        for group in UNFOLD["SIDEBAR"]["navigation"]
        for item in group["items"]
    ]
    assert "Payments" not in titles
    assert "Stripe Connect" not in titles


# --------------------------------------------------------------------------
# The ledger: emphatically still here.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/makerspace/1/payments",
        "/api/v1/admin/makerspace/1/payments/2/mark-offline",
        "/api/v1/admin/makerspace/1/payments/2/waive",
        "/api/v1/admin/makerspace/1/payments/2/amend-settlement",
        "/api/v1/admin/makerspace/1/payments/bulk/mark-offline",
        "/api/v1/member/makerspaces/1/payments",
        "/api/v1/member/archived-payments",
    ],
)
def test_every_ledger_route_still_resolves(path):
    """Money owed must stay readable and settleable with no gateway anywhere in sight.

    This is the whole point of the split: a cash-only deployment records debts, shows
    members what they owe, and lets staff settle them at the desk.
    """
    assert resolve(path) is not None


def test_the_neighbours_in_the_same_urlconf_still_resolve():
    """The splice must remove the rail routes only, not the block around them."""
    assert resolve("/api/v1/admin/memberships").url_name == "admin-memberships-roster"
    assert resolve("/api/v1/member/makerspaces/1/referrals").url_name == "member-referrals"


# --------------------------------------------------------------------------
# Data: retained.
# --------------------------------------------------------------------------

def test_payment_rows_are_still_readable():
    assert Payment.objects.count() == 0  # the table exists and answers


def test_the_payment_model_is_still_installed_for_migrations_and_purge():
    from django.apps import apps as django_apps

    assert django_apps.is_installed("apps.payments")
    assert django_apps.get_model("payments", "Payment") is Payment
