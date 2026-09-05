"""Membership plans, terms, the renewal sweep and the optional lapsed-cannot-borrow rule."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.inventory.models import InventoryProduct
from apps.makerspaces import membership_services
from apps.makerspaces.membership_plan_services import (
    cancel_term,
    create_term,
    run_membership_renewals,
    term_end,
)
from apps.makerspaces.models import (
    MakerspaceMembership,
    MakerspaceRole,
    MembershipPlan,
    MembershipTerm,
)
from apps.payments.models import Payment
from apps.presence.models import PresenceSession
from tests.module_helpers import disable_module
from tests.payments.test_models import configured_settings
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def plan(space, name="Monthly", interval="monthly", days=None, amount="10.00"):
    return MembershipPlan.objects.create(
        makerspace=space, name=name, interval=interval, custom_days=days,
        amount=Decimal(amount), currency="usd",
    )


def member(slug, space):
    user = make_user(f"{slug}-member", access_status="active")
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    return MakerspaceMembership.objects.create(
        makerspace=space, user=user, assigned_role=role, role="custom", status="active"
    )


def payments_on(space):
    space.enabled_features = ["payments.enabled", "payments.membership", "charges.enabled", "charges.membership"]
    space.save(update_fields=["enabled_features", "updated_at"])
    configured_settings(space)


# ------------------------------------------------------------------ term dates


def test_term_end_per_interval():
    space = make_space("plan-dates")
    start = timezone.now().replace(month=1, day=31)
    assert term_end(plan(space, "M"), start) == start.replace(month=2, day=28 + int(
        start.year % 4 == 0 and (start.year % 100 != 0 or start.year % 400 == 0)
    ))
    assert term_end(plan(space, "Y", "yearly"), start).year == start.year + 1
    assert term_end(plan(space, "D", "custom_days", 10), start) == start + timedelta(days=10)


def test_create_term_audits_and_chains_after_the_current_term():
    space = make_space("plan-create")
    manager = make_member("plan-create-mgr", space)
    membership = member("plan-create", space)
    monthly = plan(space)

    first = create_term(manager, membership, monthly)
    second = create_term(manager, membership, monthly)

    assert first.ends_at == term_end(monthly, first.starts_at)
    assert second.starts_at == first.ends_at
    entry = AuditLog.objects.get(action="membership.term_created", target_id=str(first.pk))
    assert entry.meta == {
        "membership_id": membership.pk, "plan_id": monthly.pk, "term_id": first.pk,
    }


def test_create_term_refuses_foreign_or_inactive_plans_and_off_module():
    space, other = make_space("plan-refuse"), make_space("plan-refuse-other")
    manager = make_member("plan-refuse-mgr", space)
    membership = member("plan-refuse", space)
    with pytest.raises(ValidationError):
        create_term(manager, membership, plan(other))
    inactive = plan(space, "Old")
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    with pytest.raises(ValidationError):
        create_term(manager, membership, inactive)
    disable_module(space, "membership")
    with pytest.raises(ValidationError):
        create_term(manager, membership, plan(space, "New"))


def test_approve_request_with_a_plan_opens_the_first_term():
    space = make_space("plan-approve")
    manager = make_member("plan-approve-mgr", space)
    joiner = make_user("plan-approve-joiner", access_status="active")
    joiner.email_verified_at = timezone.now()
    joiner.save(update_fields=["email_verified_at"])
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    request = membership_services.request_membership(joiner, space)

    membership = membership_services.approve_request(manager, request, role, plan=plan(space))

    assert membership.terms.filter(status="active").count() == 1


# ---------------------------------------------------------------- renewal sweep


def test_renewal_sweep_raises_exactly_one_charge_inside_the_window():
    space = make_space("plan-renew")
    payments_on(space)
    manager = make_member("plan-renew-mgr", space)
    membership = member("plan-renew", space)
    monthly = plan(space)
    now = timezone.now()
    term = create_term(manager, membership, monthly, starts_at=now - timedelta(days=27))
    outside = create_term(manager, membership, monthly, starts_at=now + timedelta(days=20))

    first = run_membership_renewals(now=now)
    second = run_membership_renewals(now=now)

    assert first["charged"] == 1 and second["charged"] == 0
    payment = Payment.objects.get(
        makerspace=space, subject_type=Payment.SubjectType.MEMBERSHIP_TERM, subject_id=term.pk
    )
    assert payment.amount == Decimal("10.00") and payment.member == membership.user
    term.refresh_from_db()
    outside.refresh_from_db()
    assert term.renewal_payment == payment and outside.renewal_payment is None
    assert AuditLog.objects.filter(action="membership.renewal_raised").count() == 1


def test_renewal_sweep_charges_nothing_with_tracking_off_and_expires_past_terms():
    """Tracking OFF is what stops a renewal charge existing at all.

    The online payments feature no longer decides this: with charge tracking on and no
    rail, the sweep still records the debt for staff to collect by hand. Switching
    `charges.membership` off is the "this space charges nothing" case, and it is what
    this test now pins -- expiry of past terms must keep working either way.
    """
    space = make_space("plan-renew-off")
    configured_settings(space)  # credentials alone are not consent to charge
    space.enabled_features = [
        key for key in space.enabled_features if key != "charges.membership"
    ]
    space.save(update_fields=["enabled_features", "updated_at"])
    manager = make_member("plan-renew-off-mgr", space)
    membership = member("plan-renew-off", space)
    monthly = plan(space)
    now = timezone.now()
    ending = create_term(manager, membership, monthly, starts_at=now - timedelta(days=28))
    ended = create_term(manager, membership, monthly, starts_at=now - timedelta(days=70))

    counts = run_membership_renewals(now=now)

    assert counts["charged"] == 0 and counts["expired"] == 1 and counts["skipped"] == 1
    assert not Payment.objects.filter(subject_type=Payment.SubjectType.MEMBERSHIP_TERM).exists()
    ended.refresh_from_db()
    ending.refresh_from_db()
    assert ended.status == "expired" and ending.status == "active"
    assert AuditLog.objects.filter(
        action="membership.term_expired", target_id=str(ended.pk)
    ).exists()


def test_cancel_term_cancels_its_pending_renewal_charge():
    space = make_space("plan-cancel")
    payments_on(space)
    manager = make_member("plan-cancel-mgr", space)
    membership = member("plan-cancel", space)
    now = timezone.now()
    term = create_term(manager, membership, plan(space), starts_at=now - timedelta(days=27))
    run_membership_renewals(now=now)

    cancel_term(manager, term)

    term.refresh_from_db()
    assert term.status == "cancelled"
    assert term.renewal_payment.status == Payment.Status.CANCELED
    with pytest.raises(ValidationError):
        cancel_term(manager, term)


# ---------------------------------------------------------- lapsed cannot borrow


def _submit(space, membership):
    now = timezone.now()
    PresenceSession.objects.create(
        member=membership.user, makerspace=space, membership=membership,
        started_at=now, expires_at=now + timedelta(hours=2),
    )
    product = InventoryProduct.objects.create(
        makerspace=space, name="Scope", total_quantity=2, available_quantity=2, is_public=True,
    )
    return authenticated_client(membership.user).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {"requested_for": "Bench", "items": [{"product_id": product.pk, "quantity": 1}]},
        format="json",
    )


@pytest.mark.parametrize(
    ("flag", "term_state", "expected"),
    [
        (False, "expired", 201),   # flag off: an expired term changes nothing
        (True, None, 201),         # flag on, never held a term: plans are optional
        (True, "active", 201),     # flag on, current term
        (True, "expired", 403),    # flag on, lapsed: refused like a non-member
        (True, "cancelled", 403),
    ],
)
def test_lapsed_members_cannot_borrow_only_when_set_and_only_when_lapsed(flag, term_state, expected):
    space = make_space(f"lapsed-{int(flag)}-{term_state}")
    space.lapsed_members_cannot_borrow = flag
    space.save(update_fields=["lapsed_members_cannot_borrow"])
    membership = member(space.slug, space)
    if term_state is not None:
        now = timezone.now()
        MembershipTerm.objects.create(
            membership=membership, plan=plan(space), status=term_state,
            starts_at=now - timedelta(days=40),
            ends_at=now + timedelta(days=10) if term_state == "active" else now - timedelta(days=5),
        )

    response = _submit(space, membership)

    assert response.status_code == expected, response.data
    if expected == 403:
        assert response.data["code"] == "membership_required"


# ------------------------------------------------------------------- staff API


def test_staff_plan_and_term_api_is_scoped_and_module_gated():
    space, other = make_space("plan-api"), make_space("plan-api-other")
    client = authenticated_client(make_member("plan-api-mgr", space))
    stranger = authenticated_client(make_member("plan-api-stranger", other))
    membership = member("plan-api", space)
    plans_url = reverse("admin-membership-plans", args=[space.pk])

    assert stranger.get(plans_url).status_code == 404
    created = client.post(
        plans_url,
        {"name": "Yearly", "interval": "yearly", "amount": "99.00", "currency": "EUR"},
        format="json",
    )
    assert created.status_code == 201 and created.data["currency"] == "eur"
    assert client.post(
        plans_url, {"name": "Bad", "interval": "monthly", "custom_days": 3, "amount": "1"},
        format="json",
    ).status_code == 400
    assert client.post(plans_url, {"name": "Yearly", "interval": "yearly", "amount": "1"}, format="json").status_code == 400
    assert stranger.patch(
        reverse("admin-membership-plan-detail", args=[created.data["id"]]), {"is_active": False}, format="json"
    ).status_code == 404
    assert client.patch(
        reverse("admin-membership-plan-detail", args=[created.data["id"]]), {"amount": "120.00"}, format="json"
    ).data["amount"] == "120.00"

    terms_url = reverse("admin-membership-terms", args=[membership.pk])
    assert stranger.post(terms_url, {"plan_id": created.data["id"]}, format="json").status_code == 404
    term = client.post(terms_url, {"plan_id": created.data["id"]}, format="json")
    assert term.status_code == 201 and term.data["plan_name"] == "Yearly"
    assert [row["id"] for row in client.get(terms_url).data] == [term.data["id"]]
    cancel_url = reverse("admin-membership-term-cancel", args=[term.data["id"]])
    assert stranger.post(cancel_url).status_code == 404
    assert client.post(cancel_url).data["status"] == "cancelled"

    disable_module(space, "membership")
    assert client.get(plans_url).status_code == 400
