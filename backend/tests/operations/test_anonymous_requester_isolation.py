"""Account-less requests must not collapse into one fictional person downstream.

Every anonymous submission in a makerspace points at the SAME
`Makerspace.anonymous_requester` principal, because that is what gives the request a
requester FK without inventing an account. Any report that groups by `requester_id` then
folds a hundred unrelated strangers into a single row: one "repeat offender", one "top
borrower", one restrictable user whose restriction would hit every future account-less
requester at once.

The principal is excluded from every per-PERSON ranking, and — because losing the data
entirely would be worse than naming a fake person — the damage and loss it was carrying is
reported as a separate total instead.
"""

import pytest
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItem,
    RequesterAccountability,
)
from apps.inventory.models import InventoryProduct
from apps.makerspaces.anonymous_requesters import (
    anonymous_requester_ids,
    get_or_create_anonymous_requester,
)
from apps.makerspaces.models import Makerspace
from apps.operations import reports
from apps.operations.accountability import accountability_data

pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def _member(username):
    return User.objects.create_user(
        username=username, email=f"{username}@example.test", display_name=username,
    )


def _product(space):
    return InventoryProduct.objects.create(
        makerspace=space, name="Oscilloscope", total_quantity=50, available_quantity=50,
    )


def _issued_request(space, product, requester, *, quantity=1, name="", email=""):
    request = HardwareRequest.objects.create(
        makerspace=space,
        requester=requester,
        requester_username="" if name else requester.username,
        requester_name=name,
        requester_contact_email=email,
        requester_contact_verified=not name,
        status=HardwareRequest.Status.ISSUED,
        issued_at=timezone.now(),
    )
    HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=quantity,
        accepted_quantity=quantity,
        issued_quantity=quantity,
    )
    return request


def _recorder():
    """The staffer who recorded the incident.

    Irrelevant to what these tests assert -- they are about the *requester* side -- but
    `created_by` is a non-null PROTECT FK, so every row needs one. Reused rather than
    created per call: a test records several incidents, and `username` is unique.
    """
    user, _ = User.objects.get_or_create(
        username="iso-recorder",
        defaults={
            "email": "iso-recorder@example.test",
            "display_name": "iso-recorder",
        },
    )
    return user


def _accountability(space, requester, issue_type, quantity=1):
    """An incident recorded against `requester`.

    `request` and `request_item` are both non-null on the model -- an incident is always
    against one specific issued line -- so the helper creates the loan it is recording
    rather than making every caller build one it does not otherwise care about.
    """
    request = _issued_request(space, _product(space), requester, quantity=quantity)
    return RequesterAccountability.objects.create(
        makerspace=space,
        requester=requester,
        request=request,
        request_item=HardwareRequestItem.objects.get(request=request),
        issue_type=issue_type,
        quantity=quantity,
        created_by=_recorder(),
    )


def test_the_shared_principal_never_appears_as_a_top_borrower():
    space = _space("iso-top-borrowers")
    product = _product(space)
    principal = get_or_create_anonymous_requester(space)
    member = _member("iso-real-borrower")

    _issued_request(space, product, member, quantity=1)
    # Three strangers, one principal — this is the collapse being prevented. Left in, the
    # principal would out-rank the real borrower three to one.
    for index in range(3):
        _issued_request(
            space, product, principal, quantity=5,
            name=f"Stranger {index}", email=f"stranger{index}@example.test",
        )

    rows = reports._top_borrowers(space.id, aggregate=False)

    assert rows[0] == ["holder", "requests", "items_borrowed"]
    holders = [row[0] for row in rows[1:]]
    assert holders == ["iso-real-borrower"]
    assert principal.username not in holders


def test_the_export_header_is_unchanged_by_the_exclusion():
    """The report registry pins these three columns; excluding rows must not touch them."""
    space = _space("iso-header")
    product = _product(space)
    principal = get_or_create_anonymous_requester(space)
    _issued_request(space, product, principal, name="Stranger", email="s@example.test")

    rows = reports._top_borrowers(space.id, aggregate=False)

    assert rows[0] == ["holder", "requests", "items_borrowed"]
    assert rows[1:] == []


def test_the_shared_principal_never_appears_as_a_repeat_offender():
    space = _space("iso-offenders")
    principal = get_or_create_anonymous_requester(space)
    member = _member("iso-real-offender")
    _accountability(space, member, RequesterAccountability.IssueType.DAMAGED)
    for _ in range(4):
        _accountability(space, principal, RequesterAccountability.IssueType.MISSING, quantity=2)

    data = accountability_data(space.id)

    assert [row["requester_id"] for row in data["repeat_offenders"]] == [member.id]


def test_the_excluded_damage_and_loss_is_still_reported_as_a_total():
    """Excluding the principal must not silently delete accountability history."""
    space = _space("iso-aggregate")
    principal = get_or_create_anonymous_requester(space)
    _accountability(space, principal, RequesterAccountability.IssueType.DAMAGED, quantity=2)
    _accountability(space, principal, RequesterAccountability.IssueType.MISSING, quantity=3)

    data = accountability_data(space.id)

    assert data["anonymous_accountability"] == {
        "damaged": 1, "missing": 1, "total_issues": 2, "total_quantity": 5,
    }


def test_the_aggregate_is_zero_shaped_when_there_are_no_account_less_incidents():
    space = _space("iso-aggregate-empty")
    _accountability(space, _member("iso-only-member"), RequesterAccountability.IssueType.DAMAGED)

    data = accountability_data(space.id)

    assert data["anonymous_accountability"] == {
        "damaged": 0, "missing": 0, "total_issues": 0, "total_quantity": 0,
    }


def test_an_overdue_account_less_loan_shows_the_contact_not_the_internal_username():
    """The principal's username is `member_<uuid hex>`, which tells staff nothing."""
    space = _space("iso-overdue")
    product = _product(space)
    principal = get_or_create_anonymous_requester(space)
    request = _issued_request(
        space, product, principal, name="Ada Lovelace", email="ada@example.test",
    )
    request.return_due_at = timezone.now() - timedelta(days=2)
    request.save(update_fields=["return_due_at"])

    data = accountability_data(space.id)

    overdue = [row for row in data["overdue"] if row["reference_id"] == request.id]
    assert overdue, data["overdue"]
    assert overdue[0]["requester_username"] == "Ada Lovelace"
    assert not overdue[0]["requester_username"].startswith("member_")


def test_a_restricted_principal_is_never_listed_as_a_restricted_person():
    """Restrict/restore already refuse the principal; this is the read-side backstop for
    a row written before that guard, or by a direct database edit."""
    space = _space("iso-restricted")
    principal = get_or_create_anonymous_requester(space)
    _accountability(space, principal, RequesterAccountability.IssueType.MISSING)
    User.objects.filter(pk=principal.pk).update(
        access_status=User.AccessStatus.RESTRICTED, restriction_reason="edited directly",
    )

    data = accountability_data(space.id)

    assert [row["requester_id"] for row in data["restrictions"]] == []


def test_anonymous_requester_ids_is_scoped_and_global():
    one, two = _space("iso-scope-one"), _space("iso-scope-two")
    first = get_or_create_anonymous_requester(one)
    second = get_or_create_anonymous_requester(two)

    assert anonymous_requester_ids([one.id]) == {first.id}
    assert anonymous_requester_ids() >= {first.id, second.id}
    # A makerspace that has never taken an account-less request has no principal at all.
    assert anonymous_requester_ids([_space("iso-scope-three").id]) == set()
