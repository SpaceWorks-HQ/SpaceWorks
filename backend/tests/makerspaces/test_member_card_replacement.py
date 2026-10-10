"""A revoked card can be replaced: one LIVE card per membership, not one card ever.

`MemberCard.membership` was a OneToOne, so the first revocation stranded the member: issue
refused ("already holds a card") and reissue refused ("issue a new one"). With membership
revocation now revoking the card, every revoke-then-reactivate would have hit it.
"""
import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from apps.boxes.models import QrCode
from apps.makerspaces import member_card_services as services
from apps.makerspaces import membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MemberCard
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user

pytestmark = pytest.mark.django_db


def _membership(makerspace, name):
    return MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user(name), assigned_role=member_role(makerspace), role="custom",
    )


def test_a_lost_card_is_revoked_and_a_fresh_one_issued():
    makerspace = space("card-replace")
    boss = manager(makerspace, "card-replace-manager")
    membership = _membership(makerspace, "card-replace-member")
    first = services.issue_card(boss, membership, printed_name="Ada")
    with pytest.raises(PermissionDenied):
        services.issue_card(boss, membership)  # one LIVE card

    services.revoke_card(boss, first, reason="lost")
    second = services.issue_card(boss, membership, printed_name="Ada")

    assert second.pk != first.pk and second.card_number == first.card_number + 1
    assert services.active_qr(second).status == QrCode.Status.ACTIVE
    first.refresh_from_db()
    assert first.revoked_at is not None and first.membership_id == membership.pk


def test_a_reactivated_member_can_hold_a_card_again():
    makerspace = space("card-reactivate", membership_policy=Makerspace.MembershipPolicy.OPEN)
    boss = manager(makerspace, "card-reactivate-manager")
    member = user("card-reactivate-member")
    membership_services.request_membership(member, makerspace)
    membership = MakerspaceMembership.objects.get(makerspace=makerspace, user=member)
    services.issue_card(boss, membership)

    membership_services.revoke_membership(boss, membership)
    membership_services.request_membership(member, makerspace)
    membership.refresh_from_db()

    assert membership.status == "active"
    assert services.issue_card(boss, membership).is_active


def test_the_database_refuses_two_live_cards_for_one_membership():
    makerspace = space("card-db-guard")
    membership = _membership(makerspace, "card-db-guard-member")
    MemberCard.objects.create(makerspace=makerspace, membership=membership, card_number=1)

    with pytest.raises(IntegrityError), transaction.atomic():
        MemberCard.objects.create(makerspace=makerspace, membership=membership, card_number=2)
