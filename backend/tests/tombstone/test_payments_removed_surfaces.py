"""apps/payments under the tombstone profile.

A makerspace that takes no money online ships no Stripe surfaces at all. The models stay,
because historic charges must remain readable, purgeable and nameable by the retention
registry long after the deployment stops selling anything.

The most important assertion here is the webhook one: an endpoint that still accepted and
verified a Stripe event would settle money into a system whose reconciliation console no
longer exists, and nobody would ever see it.
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
# Surfaces: gone.
# --------------------------------------------------------------------------

def test_the_app_is_registered_as_inactive():
    assert runtime_active("payments") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/webhooks/stripe/connect",
        "/api/v1/webhooks/stripe/abc123",
        "/api/v1/payments/connect/callback",
        "/api/v1/admin/makerspace/1/payments",
        "/api/v1/admin/makerspace/1/payments/bulk/mark-offline",
    ],
)
def test_no_payment_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/member/makerspaces/1/payments",
        "/api/v1/member/makerspaces/1/payments/2/checkout",
        "/api/v1/member/makerspaces/1/payments/2/mobile-intent",
    ],
)
def test_no_member_payment_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_neighbouring_member_route_still_resolves():
    match = resolve("/api/v1/member/makerspaces/1/referrals")

    assert match.url_name == "member-referrals"


def test_the_stripe_webhook_does_not_answer():
    """The one that matters: a live webhook would settle charges nothing can reconcile."""
    response = APIClient().post("/api/v1/webhooks/stripe/abc123", {}, format="json")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/platform/payment-settings",
        "/api/v1/admin/makerspace/1/payment-settings",
        "/api/v1/admin/machine-service/payments/1/waive",
    ],
)
def test_no_staff_payment_route_resolves(path):
    # These live in `admin_api`'s urlconf rather than the app's own, so they need the
    # in-place `_separable` gate instead of a dropped include().
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_neighbours_in_the_same_urlconf_still_resolve():
    """The splice must remove the payment routes only, not the block around them."""
    assert resolve("/api/v1/admin/memberships").url_name == "admin-memberships-roster"


def test_the_admin_does_not_register_the_models():
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


def test_the_frontend_is_told_the_app_is_unavailable():
    # Payments owns feature keys, not a module key, so there is no key for
    # `available_modules` to drop -- this list is how the console hides the tab.
    assert "payments" in unavailable_apps()


# --------------------------------------------------------------------------
# Data: retained.
# --------------------------------------------------------------------------

def test_payment_rows_are_still_readable():
    assert Payment.objects.count() == 0  # the table exists and answers


def test_the_payment_model_is_still_installed_for_migrations_and_purge():
    from django.apps import apps as django_apps

    assert django_apps.is_installed("apps.payments")
    assert django_apps.get_model("payments", "Payment") is Payment
