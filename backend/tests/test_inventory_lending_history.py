from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import (
    authenticated_client,
    make_member,
    make_product,
    make_space,
    make_user,
)
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def test_inventory_lending_history_returns_last_three_lends():
    makerspace = make_space("lending-history")
    other_space = make_space("lending-history-other")
    manager = make_member(
        "lending-history-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    product = make_product(makerspace, name="Thermal Camera")
    now = timezone.now()

    create_lend(makerspace, product, "oldest-borrower", now - timedelta(days=4), 1)
    create_lend(makerspace, product, "third-borrower", now - timedelta(days=3), 2)
    create_lend(makerspace, product, "second-borrower", now - timedelta(days=2), 3)
    create_lend(makerspace, product, "latest-borrower", now - timedelta(days=1), 4)
    create_lend(makerspace, product, "zero-borrower", now, 0)
    create_lend(other_space, product, "cross-tenant-borrower", now, 5)

    response = authenticated_client(manager).get(
        f"/api/v1/admin/inventory/{product.id}/lending-history"
    )

    assert response.status_code == 200
    assert response.data["product_id"] == product.id
    # The borrower label now resolves a readable identifier (email-first, matching the
    # ledger). These helper users carry a User.email, so the contactable email is shown.
    assert response.data["last_borrower"]["username"] == "latest-borrower@e.com"
    assert [item["username"] for item in response.data["recent"]] == [
        "latest-borrower@e.com",
        "second-borrower@e.com",
        "third-borrower@e.com",
    ]
    assert [item["quantity"] for item in response.data["recent"]] == [4, 3, 2]


def test_inventory_lending_history_resolves_readable_label_for_checkin_hash():
    # A self-checkout shadow user carries the privacy hash username checkin_<sha256>.
    # The history must show the readable Check-In identifier, never the hash.
    makerspace = make_space("lending-history-hash")
    manager = make_member(
        "lending-history-hash-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    product = make_product(makerspace, name="Heat Gun")
    hashed = "checkin_" + ("a" * 64)
    requester = make_user(
        hashed,
        access_status=User.AccessStatus.ACTIVE,
        external_checkin_user_id="walkin@x.com",
    )
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=hashed,
        status=HardwareRequest.Status.ISSUED,
        issued_at=timezone.now(),
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=1,
        accepted_quantity=1,
        issued_quantity=1,
    )

    response = authenticated_client(manager).get(
        f"/api/v1/admin/inventory/{product.id}/lending-history"
    )

    assert response.status_code == 200
    label = response.data["last_borrower"]["username"]
    assert not label.startswith("checkin_")
    assert label == "walkin@x.com"


def test_inventory_lending_history_is_hidden_from_guest_admin():
    makerspace = make_space("lending-history-guest")
    guest = make_handout_member("lending-history-guest-admin", makerspace)
    product = make_product(makerspace, name="Logic Probe")

    response = authenticated_client(guest).get(
        f"/api/v1/admin/inventory/{product.id}/lending-history"
    )

    assert response.status_code == 404


def test_inventory_lending_history_soft_hidden_from_superadmin():
    # A makerspace that has opted out of superadmin access must not leak borrower
    # PII to a superadmin via this endpoint (mirrors the audit/report soft-hide).
    makerspace = make_space("lending-history-hidden")
    make_member("lending-history-hidden-manager", makerspace)
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])
    superadmin = make_user(
        "lending-history-superadmin", access_status=User.AccessStatus.ACTIVE
    )
    superadmin.is_superuser = True
    superadmin.role = User.Role.SUPERADMIN
    superadmin.save(update_fields=["is_superuser", "role"])
    product = make_product(makerspace, name="Oscilloscope")
    create_lend(makerspace, product, "hidden-borrower", timezone.now(), 2)

    response = authenticated_client(superadmin).get(
        f"/api/v1/admin/inventory/{product.id}/lending-history"
    )

    assert response.status_code == 404


def create_lend(makerspace, product, username, issued_at, quantity):
    requester = make_user(username, access_status=User.AccessStatus.ACTIVE)
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=username,
        status=HardwareRequest.Status.ISSUED,
        issued_at=issued_at,
    )
    return HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=max(quantity, 1),
        accepted_quantity=quantity,
        issued_quantity=quantity,
    )
