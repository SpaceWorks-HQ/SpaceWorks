"""OFF-state contracts for identity, community, handover, and native sessions."""

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceGrant, User
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys
from tests.accounts.oidc_browser_helpers import ORIGIN, make_provider, metadata, start
from tests.accounts.test_device_auth import attested_login
from tests.handout_roles import make_handout_member
from tests.makerspaces.test_core_module_independence import (
    configuration_without,
    run_loan_spine,
)
from tests.test_admin_direct_loans import (
    authed as handout_client,
    direct_payload,
    direct_url,
    make_product as direct_product,
)


pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())
IDENTITY_MODULES = ("member_accounts", "membership", "guest_handover", "mobile")
PHONE_START = "/api/v1/auth/phone/login/start"
PASSWORD = "Safe identity password 947!"


@pytest.fixture(autouse=True)
def clear_capability_and_throttle_cache():
    """Deployment gates and anonymous throttles share cache across test requests."""
    cache.clear()
    yield
    cache.clear()


def _space(slug, *optional, anonymous=False):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=sorted(CORE | set(optional)),
        anonymous_requests_enabled=anonymous,
        public_inventory_enabled=True,
    )


def _account(slug, *, superadmin=False):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        password=PASSWORD,
        display_name="Identity Contract User",
        access_status=User.AccessStatus.ACTIVE,
        email_verified_at=timezone.now(),
        role=User.Role.SUPERADMIN if superadmin else User.Role.REQUESTER,
        is_staff=superadmin,
        is_superuser=superadmin,
    )


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def _product(space):
    return InventoryProduct.objects.create(
        makerspace=space,
        name="Identity test multimeter",
        total_quantity=2,
        available_quantity=2,
        is_public=True,
    )


def _request(space, client, *, anonymous=False):
    product = _product(space)
    payload = {
        "requested_for": "Identity off-state check",
        "items": [{"product_id": product.pk, "quantity": 1}],
    }
    headers = {}
    if anonymous:
        payload.update(
            contact_name="Account-less Borrower",
            contact_email=f"{space.slug}@example.test",
        )
        headers["HTTP_IDEMPOTENCY_KEY"] = f"{space.slug}-request"
    return client.post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        payload,
        format="json",
        **headers,
    )


def test_member_accounts_off_refuses_phone_login_but_keeps_walk_ins_and_oidc(
    monkeypatch, settings
):
    """Removing self-service identity must not remove either replacement identity path."""
    # The OIDC browser start refuses any origin that is not registered, so the member
    # origin has to be trusted here or the 403 reads as a module gate rather than the
    # CORS check it actually is.
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    space = _space("identity-member-accounts-off")
    staff = make_handout_member("identity-front-desk", space)

    phone = _client().post(
        PHONE_START, {"phone": "+15550100200"}, format="json"
    )
    walk_in = _client(staff).post(
        reverse("admin-walk-in-member-create", args=[space.pk]),
        {"display_name": "Counter Borrower"},
        format="json",
    )
    provider = make_provider()
    monkeypatch.setattr(
        "apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider)
    )
    oidc = start(_client())

    assert phone.status_code == 404
    assert walk_in.status_code == 201, walk_in.data
    assert User.objects.get(pk=walk_in.data["user_id"]).is_walk_in is True
    assert oidc.status_code == 200, oidc.data


def test_member_accounts_on_allows_the_phone_login_surface(monkeypatch):
    _space("identity-member-accounts-on", "member_accounts")
    started = []
    monkeypatch.setattr(
        "apps.accounts.views_phone.start_login", lambda phone: started.append(phone)
    )

    response = _client().post(
        PHONE_START, {"phone": "+15550100201"}, format="json"
    )

    assert response.status_code == 200, response.data
    assert started == ["+15550100201"]


def test_membership_off_refuses_join_requests_and_on_accepts_them():
    applicant = _account("identity-join-applicant")
    off = _space("identity-membership-off")
    on = _space("identity-membership-on", "membership")

    refused = _client(applicant).post(
        reverse("public-membership-request", args=[off.slug]), {}, format="json"
    )
    accepted = _client(applicant).post(
        reverse("public-membership-request", args=[on.slug]), {}, format="json"
    )

    assert refused.status_code == 400
    assert "membership is disabled" in str(refused.data)
    assert accepted.status_code == 201, accepted.data


def test_membership_off_supports_account_and_anyone_request_policies_but_on_requires_members():
    """Only reviewed proposals downgrade; installing membership closes the anonymous path."""
    account_space = _space("identity-account-policy")
    account_response = _request(
        account_space, _client(_account("identity-account-borrower"))
    )

    anyone_space = _space("identity-anyone-policy", anonymous=True)
    anyone_response = _request(anyone_space, _client(), anonymous=True)

    members_space = _space("identity-members-policy", "membership", anonymous=True)
    members_space.refresh_from_db()
    member_required = _request(
        members_space, _client(_account("identity-non-member"))
    )
    anonymous_closed = _request(members_space, _client(), anonymous=True)

    assert account_response.status_code == 201, account_response.data
    assert anyone_response.status_code == 201, anyone_response.data
    assert members_space.anonymous_requests_enabled is False
    assert member_required.status_code == 403
    assert member_required.data["code"] == "membership_required"
    assert anonymous_closed.status_code == 401
    assert HardwareRequest.objects.filter(makerspace=account_space).count() == 1
    assert HardwareRequest.objects.filter(makerspace=anyone_space).count() == 1
    assert not HardwareRequest.objects.filter(makerspace=members_space).exists()


def test_guest_handover_off_refuses_its_own_url_surface_and_on_restores_it():
    """The module owns the `guest-admin/` URL surface, nothing behind it."""
    actor = _account("identity-handover-superadmin", superadmin=True)
    off = _space("identity-guest-handover-off")
    on = _space("identity-guest-handover-on", "guest_handover")

    refused = _client(actor).get(
        reverse("hardware_requests:guest-admin-active-loans", args=[off.pk])
    )
    enabled = _client(actor).get(
        reverse("hardware_requests:guest-admin-active-loans", args=[on.pk])
    )

    assert refused.status_code == 400
    assert "guest_handover is disabled" in str(refused.data)
    assert enabled.status_code == 200, enabled.data


def test_guest_handover_off_leaves_the_admin_reviewed_request_queues_working():
    """The admin queues are `request_workflow`'s, and the SAME view class serves both URLs.

    Gating the shared view on `guest_handover` let an optional module strand every accepted
    request on a core-only install. These three admin routes have no guest-admin twin at
    all, so they must never have been gated on it.
    """
    actor = _account("identity-handover-admin-queues", superadmin=True)
    off = _space("identity-guest-handover-admin-queues")
    assert "guest_handover" not in off.enabled_modules

    for name in ("accepted-requests", "active-loans", "request-history"):
        response = _client(actor).get(
            reverse(f"hardware_requests:{name}", args=[off.pk])
        )
        assert response.status_code == 200, (name, response.status_code, response.data)


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_guest_handover_off_keeps_the_action_scoped_staff_handout_path():
    """The module owns the narrow console, not the underlying handout authority."""
    space = _space("identity-staff-handout-substitute")
    actor = make_handout_member("identity-handout-actor", space)
    product = direct_product(space)

    response = handout_client(actor).post(
        direct_url(space),
        direct_payload(items=[{"product_id": product.pk, "quantity": 1}]),
        format="json",
    )

    assert "guest_handover" not in space.enabled_modules
    assert response.status_code == 201, response.data
    assert PublicToolLoan.objects.filter(makerspace=space).count() == 1


def test_mobile_off_refuses_a_new_device_grant_but_keeps_web_login(
    settings, monkeypatch
):
    """Native pairing is optional; the same account must remain usable in a browser."""
    _space("identity-mobile-off", "member_accounts")
    user = _account("identity-mobile-off-user")

    device, _ = attested_login(_client(), user, settings, monkeypatch, password=PASSWORD)
    browser = _client().post(
        "/api/v1/auth/login",
        {"username": user.username, "password": PASSWORD, "surface": "member"},
        format="json",
    )

    assert device.status_code == 401
    assert not DeviceGrant.objects.filter(user=user).exists()
    assert browser.status_code == 200, browser.data
    assert browser.data["surface"] == "member"


def test_mobile_on_allows_a_new_attested_device_grant(settings, monkeypatch):
    _space("identity-mobile-on", "member_accounts", "mobile")
    user = _account("identity-mobile-on-user")

    response, _ = attested_login(_client(), user, settings, monkeypatch, password=PASSWORD)

    assert response.status_code == 200, response.data
    assert DeviceGrant.objects.filter(user=user).count() == 1


@pytest.mark.parametrize("missing", IDENTITY_MODULES)
def test_each_identity_module_off_leaves_the_complete_loan_spine_working(
    missing, monkeypatch,
):
    """Optional identity conveniences cannot become undeclared core-loan dependencies."""
    modules = configuration_without(missing)
    assert missing not in modules
    run_loan_spine(
        f"identity-no-{missing.replace('_', '-')}", modules, monkeypatch
    )
