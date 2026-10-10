"""An owned debt remains core; the community dashboard stays scoped to one tenant."""
from decimal import Decimal
import pytest
from django.urls import reverse

from apps.makerspaces.models import MakerspaceMembership
from tests.member_activity.test_member_dashboard_d8 import _returned_loan
from tests.makerspaces.test_membership_j1 import member_role, space, user
from tests.module_helpers import disable_module
from tests.payments.test_borrower_charge_visibility import _loan_deposit
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def test_owned_charges_remain_visible_module_off_but_revocation_refuses_the_same_debt():
    makerspace = space("money-membership-independent")
    person = user("money-membership-independent-owner")
    payment = _loan_deposit(makerspace, person)
    disable_module(makerspace, "membership")
    client = authenticated_client(person)
    url = f"/api/v1/member/makerspaces/{makerspace.pk}/payments"
    response = client.get(url)
    assert response.status_code == 200 and [row["id"] for row in response.data] == [payment.pk]
    membership = MakerspaceMembership.objects.create(makerspace=makerspace, user=person, assigned_role=member_role(makerspace), role="custom", status="revoked")
    assert client.get(url).status_code == 403
    assert membership.status == "revoked" and payment.member_id == person.pk


def test_dual_member_activity_never_contains_the_other_spaces_rows_and_revocation_refuses_it():
    home, other = space("activity-membership-home"), space("activity-membership-other")
    person = user("activity-membership-dual")
    home_row = MakerspaceMembership.objects.create(makerspace=home, user=person, assigned_role=member_role(home), role="custom")
    MakerspaceMembership.objects.create(makerspace=other, user=person, assigned_role=member_role(other), role="custom")
    _returned_loan(home, person, "Home drill", late=False)
    _returned_loan(other, person, "Other clamp", late=True)
    client = authenticated_client(person)
    url = reverse("member-activity", args=[home.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert [row["label"] for row in response.data["loan_history"]] == ["Home drill"]
    assert "Other clamp" not in str(response.data)
    MakerspaceMembership.objects.filter(pk=home_row.pk).update(status="revoked")
    refused = client.get(url)
    assert refused.status_code == 403 and refused.data["code"] == "membership_required"


def test_dashboard_groups_multiple_currencies_and_excludes_paid_and_other_members_money():
    makerspace = space("activity-multi-currency")
    person, stranger = user("activity-multi-currency-owner"), user("activity-multi-currency-stranger")
    row = MakerspaceMembership.objects.create(makerspace=makerspace, user=person, assigned_role=member_role(makerspace), role="custom")
    for currency, amount, owner, status in [
        ("usd", "10.00", person, "pending"), ("usd", "2.50", person, "pending"),
        ("inr", "300.00", person, "pending"), ("usd", "99.00", stranger, "pending"),
        ("inr", "50.00", person, "paid_offline"),
    ]:
        payment = _loan_deposit(makerspace, owner, amount=amount)
        payment.currency, payment.status = currency, status
        payment.save(update_fields=["currency", "status"])
    response = authenticated_client(person).get(reverse("member-activity", args=[makerspace.pk]))
    assert response.status_code == 200
    totals = response.data["membership_dues"]["outstanding_by_currency"]
    assert {key: Decimal(value) for key, value in totals.items()} == {"usd": Decimal("12.50"), "inr": Decimal("300.00")}
    assert row.status == "active"
