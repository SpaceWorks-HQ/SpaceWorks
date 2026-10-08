"""The membership combination matrix (audit 00-audit.md §9), one test per composed cell.

The dimensions meet at four seams -- who becomes active (`_activate_membership`), what that
costs (one post-activation charge hook plus the renewal sweep), what an active member may do
(the presence guard plus `require_current_term`), and verification (which gates nothing).
These tests pin the COMPOSED behaviour of the cells the code supports, including the two the
owner named: paid + invite-only, and free + vouch (referral).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.boxes.models import QrCode
from apps.hardware_requests.models import PublicToolLoan
from apps.inventory.models import InventoryProduct
from apps.makerspaces import member_card_services, membership_services
from apps.makerspaces.membership_plan_services import create_term
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MembershipPlan,
    MembershipRequest,
    MembershipTerm,
)
from apps.makerspaces.walk_in_services import create_walk_in_member
from apps.payments.models import ManualSettlement, Payment
from apps.presence import services as presence
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.return_helpers import authenticated_client, settlement_payload
from tests.test_public_self_checkout import (
    checkout_payload,
    checkout_url,
    make_product,
    make_qr,
    member_client,
)

pytestmark = pytest.mark.django_db(transaction=True)

TRACKING = ["charges.enabled", "charges.membership"]


def _paid_space(slug, **fields):
    """Dues tracked, no gateway: the debt is recorded, no online rail exists."""
    return space(slug, membership_dues_amount=Decimal("25.00"), enabled_features=_features(TRACKING), **fields)


def _features(extra):
    from apps.makerspaces.capabilities import default_enabled_features

    return sorted(set(default_enabled_features()) | set(extra))


def _dues(makerspace, membership):
    return Payment.objects.filter(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
    )


def _submit(makerspace, member_user):
    presence.start_session(member_user, makerspace, 60)
    product = InventoryProduct.objects.create(
        makerspace=makerspace, name="Scope", total_quantity=2, available_quantity=2, is_public=True,
    )
    return authenticated_client(member_user).post(
        reverse("hardware_requests:request-submit", args=[makerspace.slug]),
        {"requested_for": "Bench", "items": [{"product_id": product.pk, "quantity": 1}]},
        format="json",
    )


# ---------------------------------------------------------------- M7: paid + invite-only


def test_paid_invite_only_end_to_end(settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    makerspace = _paid_space("matrix-paid-invite", membership_policy=Makerspace.MembershipPolicy.INVITE_ONLY)
    boss = manager(makerspace, "matrix-paid-invite-manager")
    invitee = user("matrix-paid-invite-invitee")

    # Invite-only: the invitee cannot let themselves in.
    with pytest.raises(ValidationError, match="invite-only"):
        membership_services.request_membership(invitee, makerspace)

    invitation = membership_services.invite_membership(boss, makerspace, invitee.email, member_role(makerspace))
    claimed = authenticated_client(invitee).post(reverse("membership-invitation-claim", args=[invitation.pk]))
    assert claimed.data["outcome"] == "pending_approval"
    # Nothing is owed before the membership exists: money never precedes activation.
    assert not Payment.objects.filter(makerspace=makerspace, member=invitee).exists()

    approved = authenticated_client(boss).post(
        reverse("admin-membership-request-approve", args=[invitation.pk]),
        {"role_id": member_role(makerspace).pk}, format="json",
    )
    assert approved.status_code == 200, approved.data
    membership = MakerspaceMembership.objects.get(makerspace=makerspace, user=invitee)
    assert membership.status == "active"
    dues = _dues(makerspace, membership).get()
    # Recorded first; with no gateway there is no rail, so it waits as an unclaimed debt.
    assert (dues.status, dues.provider, dues.amount) == (
        Payment.Status.PENDING, Payment.Provider.UNCLAIMED, Decimal("25.00"),
    )
    # The member is active while the debt is outstanding: dues never gate borrowing.
    assert _submit(makerspace, invitee).status_code == 201

    settled = authenticated_client(boss).post(
        reverse("payment-reconciliation-mark-offline", args=[makerspace.pk, dues.pk]),
        settlement_payload(), format="json",
    )
    assert settled.status_code == 200, settled.data
    dues.refresh_from_db()
    assert dues.status == Payment.Status.PAID_OFFLINE
    assert ManualSettlement.objects.filter(payment=dues).count() == 1

    # A term that lapses afterwards blocks borrowing exactly where the switch says.
    plan = MembershipPlan.objects.create(makerspace=makerspace, name="Monthly", interval="monthly", amount=Decimal("10"))
    term = create_term(boss, membership, plan, starts_at=timezone.now() - timedelta(days=40))
    MembershipTerm.objects.filter(pk=term.pk).update(status=MembershipTerm.Status.EXPIRED)
    makerspace.lapsed_members_cannot_borrow = True
    makerspace.save(update_fields=["lapsed_members_cannot_borrow"])
    refused = _submit(makerspace, invitee)
    assert refused.status_code == 403 and refused.data["code"] == "membership_required"
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)
    assert member_client(invitee).post(
        checkout_url(makerspace), checkout_payload(makerspace, invitee, qr.payload), format="json",
    ).status_code == 403
    assert PublicToolLoan.objects.filter(makerspace=makerspace).count() == 0
    membership.refresh_from_db()
    assert membership.status == "active"  # lapsing is never an access state


# ----------------------------------------------------------------- M11: free + vouch


def test_free_vouched_join_activates_on_the_claim_and_never_charges():
    makerspace = space(
        "matrix-free-vouch", referrals_enabled=True, enabled_features=_features(TRACKING),
    )
    voucher = user("matrix-free-vouch-voucher")
    MakerspaceMembership.objects.create(
        makerspace=makerspace, user=voucher, assigned_role=member_role(makerspace), role="custom",
    )
    newcomer = user("matrix-free-vouch-newcomer")

    referral = membership_services.refer_membership(voucher, makerspace, newcomer.email)
    joined = membership_services.claim_invitation(newcomer, referral.pk)

    assert joined.status == "active"
    # Activation never waited on verification: vouching IS the admission.
    assert joined.verified_at is None
    # Free: dues are zero, so tracking on still records nothing.
    assert not Payment.objects.filter(makerspace=makerspace).exists()
    referral.refresh_from_db()
    assert referral.state == MembershipRequest.State.ACTIVE
    assert AuditLog.objects.filter(action="membership.referred", makerspace=makerspace).count() == 1


def test_a_referral_admits_into_an_invite_only_space():
    makerspace = space(
        "matrix-vouch-invite-only", referrals_enabled=True,
        membership_policy=Makerspace.MembershipPolicy.INVITE_ONLY,
    )
    voucher = user("matrix-vouch-io-voucher")
    MakerspaceMembership.objects.create(
        makerspace=makerspace, user=voucher, assigned_role=member_role(makerspace), role="custom",
    )
    newcomer = user("matrix-vouch-io-newcomer")

    referral = membership_services.refer_membership(voucher, makerspace, newcomer.email)

    assert membership_services.claim_invitation(newcomer, referral.pk).status == "active"


def test_referral_edges_revoked_voucher_and_an_already_active_target():
    makerspace = space("matrix-vouch-edges", referrals_enabled=True)
    voucher = user("matrix-vouch-edges-voucher")
    voucher_membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=voucher, assigned_role=member_role(makerspace), role="custom",
    )
    existing = user("matrix-vouch-edges-existing")
    MakerspaceMembership.objects.create(
        makerspace=makerspace, user=existing, assigned_role=member_role(makerspace), role="custom",
    )

    with pytest.raises(ValidationError, match="already an active member"):
        membership_services.refer_membership(voucher, makerspace, existing.email)
    membership_services.revoke_membership(manager(makerspace, "matrix-vouch-edges-boss"), voucher_membership)
    from rest_framework.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        membership_services.refer_membership(voucher, makerspace, "someone@example.test")


# ------------------------------------------------------- M2 / M18 / M20: dues elsewhere


def test_an_open_join_records_dues_like_an_approval():
    makerspace = _paid_space("matrix-open-dues", membership_policy=Makerspace.MembershipPolicy.OPEN)
    joiner = user("matrix-open-dues-joiner")

    outcome = membership_services.request_membership(joiner, makerspace)

    membership = MakerspaceMembership.objects.get(pk=outcome["membership_id"])
    assert _dues(makerspace, membership).get().status == Payment.Status.PENDING


def test_a_walk_in_on_an_invite_only_paid_space_is_admitted_and_owes_dues():
    makerspace = _paid_space("matrix-walk-in-dues", membership_policy=Makerspace.MembershipPolicy.INVITE_ONLY)
    desk = manager(makerspace, "matrix-walk-in-desk")

    membership = create_walk_in_member(desk, makerspace, display_name="Counter Visitor")

    assert membership.status == "active" and membership.user.is_walk_in
    assert _dues(makerspace, membership).get().status == Payment.Status.PENDING


def test_dues_without_a_term_never_trip_the_lapsed_rule(settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    makerspace = _paid_space("matrix-dues-no-term", membership_policy=Makerspace.MembershipPolicy.OPEN)
    makerspace.lapsed_members_cannot_borrow = True
    makerspace.save(update_fields=["lapsed_members_cannot_borrow"])
    joiner = user("matrix-dues-no-term-joiner")
    membership_services.request_membership(joiner, makerspace)

    assert _submit(makerspace, joiner).status_code == 201


# -------------------------------------------------- M17: what revocation takes with it


def test_revoking_a_membership_revokes_its_card_terms_dues_and_open_requests(monkeypatch):
    monkeypatch.setattr("apps.makerspaces.member_card_storage.delete_photo", lambda card: None)
    makerspace = _paid_space("matrix-revoke")
    boss = manager(makerspace, "matrix-revoke-manager")
    target = user("matrix-revoke-target")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=target, assigned_role=member_role(makerspace), role="custom",
    )
    from apps.makerspaces.membership_payments import create_for_active_membership

    dues = create_for_active_membership(membership, boss)
    card = member_card_services.issue_card(boss, membership, printed_name="Ada L.")
    plan = MembershipPlan.objects.create(makerspace=makerspace, name="Monthly", interval="monthly", amount=Decimal("10"))
    term = create_term(boss, membership, plan)
    from apps.makerspaces.membership_plan_services import _raise_renewal

    assert _raise_renewal(MembershipTerm.objects.select_related("membership__makerspace", "membership__user", "plan").get(pk=term.pk)) == "charged"
    renewal = Payment.objects.get(subject_type=Payment.SubjectType.MEMBERSHIP_TERM, subject_id=term.pk)
    stale = MembershipRequest.objects.create(
        makerspace=makerspace, user=target, invite_email=target.email,
        kind=MembershipRequest.Kind.INVITE, state=MembershipRequest.State.INVITED,
        invited_by=boss, assigned_role=member_role(makerspace),
    )

    membership_services.revoke_membership(boss, membership, "Left the space")

    membership.refresh_from_db()
    assert membership.revocation_reason == "Left the space"
    card.refresh_from_db()
    assert card.revoked_at is not None and card.revoked_reason == "membership_revoked"
    assert card.printed_name == ""
    assert not QrCode.objects.filter(
        target_type=QrCode.TargetType.MEMBER_CARD, target_id=card.pk, status=QrCode.Status.ACTIVE,
    ).exists()
    term.refresh_from_db()
    assert term.status == MembershipTerm.Status.CANCELLED
    renewal.refresh_from_db()
    dues.refresh_from_db()
    assert renewal.status == dues.status == Payment.Status.CANCELED
    stale.refresh_from_db()
    assert stale.state == MembershipRequest.State.REVOKED


def test_revocation_takes_the_card_with_it_even_with_the_module_off(monkeypatch):
    from tests.module_helpers import disable_module

    makerspace = space("matrix-revoke-off")
    boss = manager(makerspace, "matrix-revoke-off-manager")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("matrix-revoke-off-target"),
        assigned_role=member_role(makerspace), role="custom",
    )
    card = member_card_services.issue_card(boss, membership)
    disable_module(makerspace, "membership")

    membership_services.revoke_membership(boss, membership)

    card.refresh_from_db()
    assert card.revoked_at is not None


def test_an_invitation_for_an_active_member_is_refused():
    makerspace = space("matrix-invite-active")
    boss = manager(makerspace, "matrix-invite-active-manager")
    existing = user("matrix-invite-active-member")
    MakerspaceMembership.objects.create(
        makerspace=makerspace, user=existing, assigned_role=member_role(makerspace), role="custom",
    )

    with pytest.raises(ValidationError, match="already an active member"):
        membership_services.invite_membership(boss, makerspace, existing.email, member_role(makerspace))


def test_a_revoked_membership_cannot_be_given_a_delegation():
    makerspace = space("matrix-delegate-revoked")
    boss = manager(makerspace, "matrix-delegate-revoked-manager")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("matrix-delegate-revoked-target"),
        assigned_role=member_role(makerspace), role="custom", status="revoked",
    )

    with pytest.raises(ValidationError):
        membership_services.set_can_refer(boss, membership, True)
    # Clearing one is always allowed.
    assert membership_services.set_can_refer(boss, membership, False).can_refer is False
