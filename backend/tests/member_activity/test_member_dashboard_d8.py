"""The member dashboard's history, money and notices (owner decision D8).

Gated on the `membership` module, so it is off by default: managed hosting installs the
module, a self-host deployment may install it as an add-on, and there is one code path.

Notices are DERIVED from the member's own rows. `notifications.Notification` is
makerspace-wide -- no recipient column, one shared `read_at` -- so serving it to members
would hand them staff alerts and let one member's read mark speak for everyone.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItem,
    PublicToolLoan,
)
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


def _space(slug, *, membership_module=True):
    modules = ["public_inventory", "request_workflow", "staff_admin", "scanner",
               "evidence_uploads", "qr_management"]
    if membership_module:
        modules.append("membership")
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=sorted(set(modules))
    )


def _member(space, username):
    user = User.objects.create_user(
        username=username, display_name=username,
        email=f"{username}@example.test", phone="9999999999",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        makerspace=space, user=user,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
        role="custom",
    )
    return user


def _client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def _url(space):
    return f"/api/v1/member/makerspaces/{space.id}/activity"


def _returned_loan(space, user, label, *, late):
    request = HardwareRequest.objects.create(
        makerspace=space, requester=user, requester_username=user.username,
    )
    due = timezone.now() - timedelta(days=2)
    return PublicToolLoan.objects.create(
        makerspace=space, request=request, requester=user, target_type="product",
        target_id=1, target_label=label, due_at=due,
        status=PublicToolLoan.Status.RETURNED,
        returned_at=due + timedelta(days=1 if late else -1),
    )


def test_history_is_member_owned_and_records_what_came_back():
    space = _space("dash-history")
    user, other = _member(space, "dash-owner"), _member(space, "dash-other")
    _returned_loan(space, user, "My drill", late=True)
    _returned_loan(space, other, "Their drill", late=False)
    product = InventoryProduct.objects.create(
        makerspace=space, name="Clamp", total_quantity=3, available_quantity=3
    )
    request = HardwareRequest.objects.create(
        makerspace=space, requester=user, requester_username=user.username,
        status=HardwareRequest.Status.RETURNED,
    )
    HardwareRequestItem.objects.create(
        request=request, product=product, requested_quantity=2,
        accepted_quantity=2, returned_quantity=1, damaged_quantity=1,
    )

    payload = _client(user).get(_url(space)).data

    assert [row["label"] for row in payload["loan_history"]] == ["My drill"]
    assert payload["loan_history"][0]["returned_late"] is True
    # Two requests: the reviewed one above, plus the one the self-checkout loan carries.
    # Both are the member's own, and neither is the other member's.
    assert len(payload["request_history"]) == 2
    returned = next(
        row for row in payload["request_history"] if row["status"] == "returned"
    )
    assert returned["returned_quantity"] == 1
    assert returned["damaged_quantity"] == 1


def test_dues_are_grouped_by_currency_and_never_summed_across_them():
    space = _space("dash-dues")
    space.membership_dues_amount = Decimal("15.00")
    space.save(update_fields=["membership_dues_amount", "updated_at"])
    user = _member(space, "dash-dues-member")
    membership = MakerspaceMembership.objects.get(makerspace=space, user=user)
    for currency, amount, subject in (("usd", "10.00", membership.pk),):
        Payment.objects.create(
            makerspace=space,
            subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            subject_id=subject, member=user, amount=Decimal(amount),
            currency=currency, created_by=user,
        )

    payload = _client(user).get(_url(space)).data

    assert payload["membership_dues"]["dues_amount"] == "15.00"
    assert payload["membership_dues"]["outstanding_by_currency"] == {"usd": "10.00"}


def test_notices_surface_the_members_own_overdue_loan_and_debt():
    space = _space("dash-notices")
    user = _member(space, "dash-notice-member")
    request = HardwareRequest.objects.create(
        makerspace=space, requester=user, requester_username=user.username,
    )
    PublicToolLoan.objects.create(
        makerspace=space, request=request, requester=user, target_type="product",
        target_id=1, target_label="Overdue saw",
        due_at=timezone.now() - timedelta(days=1),
    )
    membership = MakerspaceMembership.objects.get(makerspace=space, user=user)
    Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk, member=user, amount=Decimal("7.50"),
        currency="inr", created_by=user,
    )

    payload = _client(user).get(_url(space)).data
    events = [notice["event"] for notice in payload["notices"]]

    assert "loan_overdue" in events
    assert "payment_due" in events
    # Most urgent first: an overdue item outranks an unpaid charge.
    assert events.index("loan_overdue") < events.index("payment_due")


def test_a_quiet_member_gets_no_notices():
    """The feed must stay empty rather than inventing reassurance to display."""
    space = _space("dash-quiet")
    user = _member(space, "dash-quiet-member")

    payload = _client(user).get(_url(space)).data

    assert payload["notices"] == []


def test_the_dashboard_does_not_exist_without_the_membership_module():
    space = _space("dash-no-module", membership_module=False)
    user = _member(space, "dash-no-module-member")

    response = _client(user).get(_url(space))

    assert response.status_code == 400
