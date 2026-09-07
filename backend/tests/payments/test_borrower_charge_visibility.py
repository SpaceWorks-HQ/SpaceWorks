"""The admit path of the widened member payment-visibility check (D8).

`member_may_see_own_charges` was widened so an account-only BORROWER can read a debt
raised in their own name: a loan deposit or late fee is charged to whoever borrowed the
hardware, and borrowing needs an active account rather than a membership. Before the
widening those people were told "an active membership is required" about their own money.

The refusal paths (revoked membership, blocked account) are covered in
`test_archived_space_payments.py`. This file covers the ADMIT path and its edges, because
widening a money surface is where a scoping check gets quietly lost.
"""

from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment
from tests.return_helpers import (
    authenticated_client,
    make_accepted_request,
    make_product,
    make_space,
    make_user,
)


pytestmark = pytest.mark.django_db


def _loan_deposit(space, borrower, *, amount="25.00"):
    """A deposit charged against a real hardware request, as the model requires."""
    request = make_accepted_request(space, make_product(space), 1)
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.LOAN_DEPOSIT,
        subject_id=request.pk,
        member=borrower,
        amount=Decimal(amount),
        currency="usd",
        created_by=borrower,
        provider=Payment.Provider.UNCLAIMED,
        subject_label="Loan deposit",
    )


def _borrower(space, username):
    """An active account with NO membership in the space -- the whole point here."""
    user = make_user(username, access_status=User.AccessStatus.ACTIVE)
    assert not MakerspaceMembership.objects.filter(makerspace=space, user=user).exists()
    return user


def test_account_only_borrower_reads_the_debt_in_their_own_name():
    space = make_space("borrower-charge-visible")
    borrower = _borrower(space, "borrower-charge-visible-user")
    payment = _loan_deposit(space, borrower)

    response = authenticated_client(borrower).get(
        f"/api/v1/member/makerspaces/{space.pk}/payments"
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [payment.pk]
    assert response.data[0]["amount"] == "25.00"


def test_an_account_with_no_charge_here_is_still_refused():
    """Owning a charge is what admits; being signed in is not."""
    space = make_space("borrower-charge-none")
    stranger = _borrower(space, "borrower-charge-none-user")

    response = authenticated_client(stranger).get(
        f"/api/v1/member/makerspaces/{space.pk}/payments"
    )

    assert response.status_code == 403
    assert response.data == {
        "detail": "An active membership or an existing charge is required."
    }


def test_one_borrowers_charge_never_admits_another_borrower():
    """The admit path is ownership-scoped, so it can only ever show the caller's own."""
    space = make_space("borrower-charge-scoped")
    owner = _borrower(space, "borrower-charge-scoped-owner")
    other = _borrower(space, "borrower-charge-scoped-other")
    _loan_deposit(space, owner)

    response = authenticated_client(other).get(
        f"/api/v1/member/makerspaces/{space.pk}/payments"
    )

    assert response.status_code == 403


def test_a_restricted_borrower_is_refused_their_own_charge():
    """The widening kept every account-status clause: restriction still shuts the door."""
    space = make_space("borrower-charge-restricted")
    borrower = _borrower(space, "borrower-charge-restricted-user")
    _loan_deposit(space, borrower)
    borrower.access_status = User.AccessStatus.RESTRICTED
    borrower.save(update_fields=["access_status"])

    response = authenticated_client(borrower).get(
        f"/api/v1/member/makerspaces/{space.pk}/payments"
    )

    assert response.status_code == 403
