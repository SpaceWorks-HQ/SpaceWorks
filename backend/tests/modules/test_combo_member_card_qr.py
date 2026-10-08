"""membership member cards x every INVENTORY QR path (matrix R10, R11, S4).

A member-card QR is a `boxes.QrCode` like any other, but its `target_id` is a
MemberCard pk and it is an identity credential under `manage_member_cards`. Every
inventory surface must treat it as an unknown payload. The dangerous case is a pk
collision: the self-checkout target resolver used to send every non-product/asset QR to
the BOX branch, so a member scanning their own ID card checked out whichever public box
shared the card's number.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.hardware_requests.models import PublicToolLoan
from apps.makerspaces import member_card_services as cards
from apps.makerspaces.models import MakerspaceMembership
from apps.operations.models import StocktakeSession
from tests.test_box_checkout_integrity import (
    checkout_payload,
    direct_payload,
    direct_url,
    eligible_member,
    make_admin,
    make_product,
    make_space,
    member_client,
    public_checkout_url,
)

pytestmark = pytest.mark.django_db


def _card_and_colliding_box(space, member, manager):
    """Issue `member` a card, then build a public, loanable box whose pk is the card's."""
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    card = cards.issue_card(manager, membership)
    box = Box.objects.create(pk=card.pk, makerspace=space, label="Collides with the card")
    make_product(space, name="Kit in the colliding box", box=box)
    return card, cards.active_qr(card), box


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_self_checkout_refuses_a_member_card_even_when_a_box_shares_its_pk():
    space = make_space("combo-card-self-checkout")
    manager = make_admin(space)
    member = eligible_member(space, "combo-card-member")
    _card, qr, box = _card_and_colliding_box(space, member, manager)

    response = member_client(member).post(
        public_checkout_url(space), checkout_payload(space, member, qr.payload), format="json"
    )

    assert response.status_code == 400, response.data
    assert not PublicToolLoan.objects.filter(container=box).exists()
    assert not PublicToolLoan.objects.exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_handout_refuses_a_member_card_payload():
    space = make_space("combo-card-direct")
    manager = make_admin(space)
    borrower = eligible_member(space, "combo-card-borrower")
    _card, qr, _box = _card_and_colliding_box(space, borrower, manager)
    client = APIClient()
    client.force_authenticate(manager)

    response = client.post(
        direct_url(space), direct_payload(space, borrower, qr_payloads=[qr.payload]), format="json"
    )

    assert response.status_code == 400, response.data
    assert not PublicToolLoan.objects.exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_generic_qr_endpoints_never_touch_a_member_card():
    """`manage_qr` is an inventory action; the card belongs to `manage_member_cards`."""
    space = make_space("combo-card-generic")
    manager = make_admin(space)
    member = eligible_member(space, "combo-card-generic-member")
    card, qr, _box = _card_and_colliding_box(space, member, manager)
    product = make_product(space, name="Rebind target")
    client = APIClient()
    client.force_authenticate(manager)
    scans_before = QrScanEvent.objects.count()

    scan = client.post(
        "/api/v1/admin/qr/scan", {"payload": qr.payload, "context": "issue"}, format="json"
    )
    printed = client.get(f"/api/v1/admin/qr/{qr.pk}/print")
    revoked = client.post(f"/api/v1/admin/qr/{qr.pk}/revoke", {}, format="json")
    rebound = client.post(
        f"/api/v1/admin/qr/{qr.pk}/rebind-target",
        {"target_type": "product", "target_id": product.pk},
        format="json",
    )
    stocktake = StocktakeSession.objects.create(makerspace=space, started_by=manager)
    resolved = client.post(
        f"/api/v1/admin/stocktakes/{stocktake.pk}/resolve-scan",
        {"payload": qr.payload},
        format="json",
    )

    assert [scan.status_code, printed.status_code, revoked.status_code,
            rebound.status_code, resolved.status_code] == [404] * 5
    qr.refresh_from_db()
    assert qr.status == QrCode.Status.ACTIVE
    assert (qr.target_type, qr.target_id) == (QrCode.TargetType.MEMBER_CARD, card.pk)
    assert QrScanEvent.objects.count() == scans_before
    # The dedicated resolver still works for the action that owns it.
    assert cards.resolve(manager, space, qr.payload)["card_number"] == card.card_number


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_a_real_box_qr_still_checks_out_through_the_same_resolver():
    """Control: the explicit BOX branch keeps the ordinary container checkout working."""
    space = make_space("combo-card-box-control")
    member = eligible_member(space, "combo-card-box-member")
    box = Box.objects.create(makerspace=space, label="Ordinary box")
    make_product(space, name="Ordinary kit", box=box)
    qr = QrCode.objects.create(
        makerspace=space, target_type=QrCode.TargetType.BOX, target_id=box.pk
    )

    response = member_client(member).post(
        public_checkout_url(space), checkout_payload(space, member, qr.payload), format="json"
    )

    assert response.status_code == 201, response.data
    assert PublicToolLoan.objects.get().container == box
