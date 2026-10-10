"""A member can see their own plan term and is told when it lapses (audit §4).

Before this, nothing member-facing read `MembershipTerm`: with `lapsed_members_cannot_borrow`
on, a member was refused borrowing with no explanation anywhere they could see. The notice
derives from the member's own term row, never from `notifications.Notification`.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm
from apps.payments.models import Payment
from tests.member_activity.test_member_dashboard_d8 import _client, _member, _space, _url

pytestmark = pytest.mark.django_db


def _term(space, user, *, status="active", ends_in_days=30, plan_name="Monthly"):
    plan, _ = MembershipPlan.objects.get_or_create(
        makerspace=space, name=plan_name, defaults={"interval": "monthly", "amount": Decimal("10")},
    )
    now = timezone.now()
    return MembershipTerm.objects.create(
        membership=MakerspaceMembership.objects.get(makerspace=space, user=user), plan=plan,
        status=status, starts_at=now - timedelta(days=30), ends_at=now + timedelta(days=ends_in_days),
    )


def _events(payload):
    return {notice["event"]: notice for notice in payload["notices"]}


def test_a_member_with_no_term_sees_none_and_no_term_notice():
    space = _space("term-none")
    user = _member(space, "term-none-member")

    payload = _client(user).get(_url(space)).data

    assert payload["membership_term"] is None
    assert not {"term_lapsed", "term_ending_soon"} & set(_events(payload))


def test_a_current_term_is_shown_and_warns_only_inside_the_window():
    space = _space("term-current")
    user = _member(space, "term-current-member")
    _term(space, user, ends_in_days=30)
    far = _client(user).get(_url(space)).data
    assert far["membership_term"]["current"] is True
    assert far["membership_term"]["plan_name"] == "Monthly"
    assert "term_ending_soon" not in _events(far)

    MembershipTerm.objects.update(ends_at=timezone.now() + timedelta(days=3))
    near = _client(user).get(_url(space)).data
    assert _events(near)["term_ending_soon"]["level"] == "info"


@pytest.mark.parametrize(("blocks", "level"), [(False, "warning"), (True, "critical")])
def test_a_lapsed_term_is_explained_and_says_whether_borrowing_is_blocked(blocks, level):
    space = _space(f"term-lapsed-{int(blocks)}")
    space.lapsed_members_cannot_borrow = blocks
    space.save(update_fields=["lapsed_members_cannot_borrow"])
    user = _member(space, f"term-lapsed-{int(blocks)}-member")
    # Still ACTIVE in the row (sweep not yet run) but past `ends_at`: the borrowing rule
    # treats it as lapsed, so the dashboard must too.
    _term(space, user, status="active", ends_in_days=-1)

    payload = _client(user).get(_url(space)).data

    assert payload["membership_term"]["current"] is False
    assert payload["membership_term"]["blocks_borrowing"] is blocks
    assert _events(payload)["term_lapsed"]["level"] == level


def test_another_members_term_never_shows():
    space = _space("term-isolation")
    reader = _member(space, "term-isolation-reader")
    other = _member(space, "term-isolation-other")
    _term(space, other, ends_in_days=-1)

    assert _client(reader).get(_url(space)).data["membership_term"] is None


def test_outstanding_money_is_reported_per_currency_and_never_summed():
    space = _space("term-two-currencies")
    user = _member(space, "term-two-currencies-member")
    membership = MakerspaceMembership.objects.get(makerspace=space, user=user)
    terms = [_term(space, user, plan_name=name) for name in ("Monthly", "Yearly")]
    for term, (amount, currency) in zip(terms, [("10.00", "usd"), ("500.00", "inr")]):
        Payment.objects.create(
            makerspace=space, member=user, amount=Decimal(amount), currency=currency,
            subject_type=Payment.SubjectType.MEMBERSHIP_TERM, subject_id=term.pk,
            provider=Payment.Provider.UNCLAIMED, created_by=user,
            subject_label="Membership renewal",
        )
    assert membership.pk

    dues = _client(user).get(_url(space)).data["membership_dues"]

    assert dues["outstanding_by_currency"] == {"inr": "500.00", "usd": "10.00"}
