"""B1: request proposals stay usable when the community membership module is off.

Only public borrow-request submission gets this narrow exception. The other guarded
surfaces move hardware, reserve facility capacity, or create member participation, so
their tenant-binding MakerspaceMembership requirement is pinned below.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event
from apps.hardware_requests.models import HardwareRequest
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceWaiver
from apps.makerspaces.module_profiles import EVERYTHING, RECOMMENDED, profile_modules


pytestmark = pytest.mark.django_db


def _space(slug, modules):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=modules,
        enabled_features=["inventory.self_checkout"],
    )


def _user(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        display_name=username,
        phone="+15550101010",
    )


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def _product(space):
    return InventoryProduct.objects.create(
        makerspace=space,
        name="Logic analyzer",
        total_quantity=1,
        available_quantity=1,
        is_public=True,
    )


def _request_payload(product):
    return {
        "requested_for": "Bench diagnostics",
        "items": [{"product_id": product.pk, "quantity": 1}],
    }


def test_membership_off_allows_an_authenticated_non_member_to_submit_request():
    modules = profile_modules(RECOMMENDED)
    assert "membership" not in modules
    space = _space("request-membership-off", modules)
    product = _product(space)
    MakerspaceWaiver.objects.create(
        makerspace=space,
        is_active=True,
        version="1",
        body="Staff acceptance controls this proposal path.",
    )

    response = _client(_user("request-outsider")).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        _request_payload(product),
        format="json",
    )

    assert response.status_code == 201, response.data
    assert HardwareRequest.objects.filter(makerspace=space).count() == 1


def test_membership_on_still_refuses_an_authenticated_non_member():
    space = _space("request-membership-on", profile_modules(EVERYTHING))
    product = _product(space)

    response = _client(_user("request-non-member")).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        _request_payload(product),
        format="json",
    )

    assert response.status_code == 403
    assert response.data["code"] == "membership_required"
    assert not HardwareRequest.objects.filter(makerspace=space).exists()


def test_membership_off_request_submission_still_requires_authentication():
    space = _space("request-anonymous", profile_modules(RECOMMENDED))

    response = _client().post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        _request_payload(_product(space)),
        format="json",
    )

    assert response.status_code == 401
    assert not HardwareRequest.objects.filter(makerspace=space).exists()


def test_membership_off_does_not_relax_other_physical_action_surfaces():
    """A future consistency cleanup must not widen these cross-tenant actions."""
    modules = [key for key in profile_modules(EVERYTHING) if key != "membership"]
    space = _space("physical-actions-stay-member-only", modules)
    client = _client(_user("physical-action-outsider"))
    # Self-checkout is the requester PHYSICALLY taking and returning a tool, so it stays
    # member-only whether or not the community module is installed.
    urls = [
        reverse("hardware_requests:public-tool-evidence-url", args=[space.slug]),
        reverse("hardware_requests:public-tool-checkout", args=[space.slug]),
        reverse("hardware_requests:public-tool-return", args=[space.slug]),
    ]

    for url in urls:
        response = client.post(url, {}, format="json")
        assert response.status_code == 403, (url, response.data)
        assert response.data["code"] == "membership_required", (url, response.data)


def test_membership_off_lets_an_account_propose_machine_and_printer_service():
    """The machine/printer service submits are PROPOSALS, not physical custody.

    They deliberately mirror the public borrow request: a membership when that module is
    installed, an active account otherwise. Asserting `membership_required` here instead
    is what let the `recommended` profile ship a surface that refused every ordinary
    account -- `recommended` has `machine_service` and no `membership`.
    """
    modules = [key for key in profile_modules(EVERYTHING) if key != "membership"]
    space = _space("service-proposals-take-accounts", modules)
    urls = [
        reverse("public-machine-service-request-submit", args=[space.slug]),
        reverse("public-printer-service-upload", args=[space.slug]),
        reverse("public-printer-service-request", args=[space.slug]),
    ]

    client = _client(_user("service-proposal-account"))
    for url in urls:
        response = client.post(url, {}, format="json")
        # Past the identity gate and into validation -- never a membership refusal.
        assert response.status_code == 400, (url, response.data)
        assert response.data.get("code") != "membership_required", (url, response.data)

    # ...but still not open to the public: no account, no proposal.
    for url in urls:
        response = _client().post(url, {}, format="json")
        assert response.status_code in (401, 403), (url, response.data)


def test_membership_off_does_not_relax_event_registration():
    modules = [key for key in profile_modules(EVERYTHING) if key != "membership"]
    space = _space("events-stay-member-only", modules)
    starts_at = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=space,
        title="Safety induction",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        is_public=True,
        status=Event.Status.PUBLISHED,
    )

    response = _client(_user("event-outsider")).post(
        reverse("public-event-register", args=[space.slug, event.public_token]),
        {},
        format="json",
    )

    assert response.status_code == 403
    assert response.data["code"] == "membership_required"
