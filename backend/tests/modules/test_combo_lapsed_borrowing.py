"""membership plans (`lapsed_members_cannot_borrow`) x every borrow path (matrix R6, R7, R8).

The rule was enforced only on the reviewed-request submit, so a member it refused at the
request form could still check a QR tool out themselves, or be handed one at the desk.
It now applies to all three borrow paths, never to a return, and is inert with the
`membership` module uninstalled (plans are that module's state).
"""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.boxes.models import QrCode
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import PublicToolLoan
from apps.makerspaces.models import MakerspaceMembership, MembershipTerm
from tests.makerspaces.test_membership_plans import plan
from tests.module_helpers import disable_module
from tests.test_box_checkout_integrity import (
    _evidence,
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


def _space(slug, *, flag=True):
    space = make_space(slug)
    space.lapsed_members_cannot_borrow = flag
    space.save(update_fields=["lapsed_members_cannot_borrow"])
    return space


def _term(space, user, state):
    membership = MakerspaceMembership.objects.get(makerspace=space, user=user)
    now = timezone.now()
    return MembershipTerm.objects.create(
        membership=membership, plan=plan(space), status=state,
        starts_at=now - timedelta(days=40),
        ends_at=now + timedelta(days=10) if state == "active" else now - timedelta(days=5),
    )


def _product_qr(space):
    product = make_product(space, name="Lapsed-rule drill")
    return QrCode.objects.create(
        makerspace=space, target_type=QrCode.TargetType.PRODUCT, target_id=product.pk
    )


def _checkout(space, member, qr):
    return member_client(member).post(
        public_checkout_url(space), checkout_payload(space, member, qr.payload), format="json"
    )


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
@pytest.mark.parametrize(
    ("flag", "term_state", "expected"),
    [
        (False, "expired", 201),
        (True, None, 201),
        (True, "active", 201),
        (True, "expired", 403),
        (True, "cancelled", 403),
    ],
)
def test_self_checkout_obeys_the_lapsed_rule(flag, term_state, expected):
    space = _space(f"combo-lapsed-self-{int(flag)}-{term_state}", flag=flag)
    member = eligible_member(space, "combo-lapsed-self")
    if term_state is not None:
        _term(space, member, term_state)

    response = _checkout(space, member, _product_qr(space))

    assert response.status_code == expected, response.data
    if expected == 403:
        assert response.data["code"] == "membership_required"
        assert not PublicToolLoan.objects.exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_staff_direct_handout_obeys_the_lapsed_rule_for_the_borrower():
    space = _space("combo-lapsed-direct")
    admin = make_admin(space)
    borrower = eligible_member(space, "combo-lapsed-borrower")
    _term(space, borrower, "expired")
    product = make_product(space, name="Desk drill")
    client = APIClient()
    client.force_authenticate(admin)

    response = client.post(
        direct_url(space),
        direct_payload(space, borrower, items=[{"product_id": product.pk, "quantity": 1}]),
        format="json",
    )

    assert response.status_code == 403, response.data
    assert response.data["code"] == "membership_required"
    assert not PublicToolLoan.objects.exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_a_member_who_lapses_mid_loan_can_still_return_the_tool():
    space = _space("combo-lapsed-return")
    member = eligible_member(space, "combo-lapsed-returner")
    term = _term(space, member, "active")
    qr = _product_qr(space)
    assert _checkout(space, member, qr).status_code == 201
    term.status = "expired"
    term.ends_at = timezone.now() - timedelta(days=1)
    term.save(update_fields=["status", "ends_at"])

    response = member_client(member).post(
        f"/api/v1/public/{space.slug}/tools/return",
        {
            "payload": qr.payload,
            "evidence_id": _evidence(space, member, EvidencePhoto.EvidenceType.RETURN).id,
            "remark": "Back on the shelf.",
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    assert PublicToolLoan.objects.get().status == PublicToolLoan.Status.RETURNED


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_self_checkout_with_membership_uninstalled_still_needs_a_member_but_not_a_term():
    """R8: the module gates the community layer, not who a hardware loan goes to."""
    space = _space("combo-lapsed-module-off")
    member = eligible_member(space, "combo-lapsed-module-off")
    _term(space, member, "expired")
    disable_module(space, "membership")
    space.refresh_from_db()
    assert "membership" not in space.enabled_modules

    response = _checkout(space, member, _product_qr(space))

    assert response.status_code == 201, response.data
    outsider = eligible_member(make_space("combo-lapsed-elsewhere"), "combo-lapsed-outsider")
    refused = _checkout(space, outsider, _product_qr(space))
    assert refused.status_code == 403, refused.data
