"""`lapsed_members_cannot_borrow` covers every way a member TAKES a tool, and is configurable.

Before this file the rule had one call site (request submission), so a lapsed member could
still self-check-out a tool or be handed one at the desk, and the staff console toggle never
rendered because the settings serializer did not carry the field.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import PublicToolLoan
from apps.makerspaces.models import MembershipPlan, MembershipTerm
from tests.module_helpers import disable_module
from tests.test_admin_direct_loans import (
    authed,
    direct_payload,
    direct_url,
    make_admin,
)
from tests.test_admin_direct_loans import eligible_member as direct_member
from tests.test_admin_direct_loans import make_product as direct_product
from tests.test_public_self_checkout import (
    checkout_payload,
    checkout_url,
    eligible_member,
    evidence_url,
    make_product,
    make_qr,
    make_space,
    member_client,
    return_payload,
    return_url,
)

pytestmark = pytest.mark.django_db


def _lapse(makerspace, user, *, status="expired", ends_in_days=-5):
    makerspace.lapsed_members_cannot_borrow = True
    makerspace.save(update_fields=["lapsed_members_cannot_borrow"])
    membership = user.makerspace_memberships.get(makerspace=makerspace)
    plan = MembershipPlan.objects.create(
        makerspace=makerspace, name="Monthly", interval="monthly", amount=Decimal("10.00"),
    )
    now = timezone.now()
    return MembershipTerm.objects.create(
        membership=membership, plan=plan, status=status,
        starts_at=now - timedelta(days=40), ends_at=now + timedelta(days=ends_in_days),
    )


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
@pytest.mark.parametrize(
    ("status", "ends_in_days", "refused"),
    [
        ("expired", -5, True),
        ("cancelled", -5, True),
        # The sweep has not run yet: still ACTIVE, but `ends_at` has passed.
        ("active", -1, True),
        ("active", 10, False),
    ],
)
def test_self_checkout_follows_the_lapsed_rule(status, ends_in_days, refused):
    makerspace = make_space(f"lapsed-sc-{status}-{ends_in_days}".replace("-", "x"))
    user = eligible_member(makerspace)
    _lapse(makerspace, user, status=status, ends_in_days=ends_in_days)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)

    response = member_client(user).post(
        checkout_url(makerspace), checkout_payload(makerspace, user, qr.payload), format="json",
    )

    if refused:
        assert response.status_code == 403, response.data
        assert response.data["code"] == "membership_required"
        assert PublicToolLoan.objects.count() == 0
    else:
        assert response.status_code == 201, response.data


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_a_lapsed_member_cannot_presign_issue_evidence_but_can_presign_a_return(monkeypatch):
    monkeypatch.setattr(
        "apps.hardware_requests.self_checkout_views.presigned_upload",
        lambda key, content_type: {"url": "https://storage.test/upload", "fields": {}},
    )
    makerspace = make_space("lapsed-presign")
    user = eligible_member(makerspace)
    _lapse(makerspace, user)
    client = member_client(user)

    issue = client.post(
        evidence_url(makerspace),
        {"evidence_type": EvidencePhoto.EvidenceType.ISSUE, "content_type": "image/png"},
        format="json",
    )
    returned = client.post(
        evidence_url(makerspace),
        {"evidence_type": EvidencePhoto.EvidenceType.RETURN, "content_type": "image/png"},
        format="json",
    )

    assert issue.status_code == 403 and issue.data["code"] == "membership_required"
    assert returned.status_code == 201, returned.data


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_a_member_who_lapses_mid_loan_can_still_return_the_tool():
    makerspace = make_space("lapsed-return")
    user = eligible_member(makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)
    client = member_client(user)
    assert client.post(
        checkout_url(makerspace), checkout_payload(makerspace, user, qr.payload), format="json",
    ).status_code == 201

    _lapse(makerspace, user)
    returned = client.post(
        return_url(makerspace), return_payload(makerspace, user, qr.payload), format="json",
    )

    assert returned.status_code == 200, returned.data
    assert PublicToolLoan.objects.get().status == PublicToolLoan.Status.RETURNED


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_staff_cannot_hand_a_tool_to_a_lapsed_member():
    makerspace = make_space("lapsed-direct")
    admin = make_admin(makerspace)
    borrower = direct_member(makerspace)
    _lapse(makerspace, borrower)
    product = direct_product(makerspace)

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(borrower=borrower, items=[{"product_id": product.id, "quantity": 1}]),
        format="json",
    )

    assert response.status_code == 403, response.data
    assert PublicToolLoan.objects.count() == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_the_rule_is_inert_while_the_membership_module_is_off():
    makerspace = make_space("lapsed-module-off")
    admin = make_admin(makerspace)
    borrower = direct_member(makerspace)
    _lapse(makerspace, borrower)
    disable_module(makerspace, "membership")
    product = direct_product(makerspace)

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(borrower=borrower, items=[{"product_id": product.id, "quantity": 1}]),
        format="json",
    )

    assert response.status_code == 201, response.data


def test_a_space_manager_can_read_and_set_the_switch_and_it_is_audited():
    makerspace = make_space("lapsed-settings")
    admin = make_admin(makerspace)
    client = authed(admin)
    url = f"/api/v1/admin/makerspaces/{makerspace.id}"

    assert client.get(url).data["lapsed_members_cannot_borrow"] is False
    response = client.patch(url, {"lapsed_members_cannot_borrow": True}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["lapsed_members_cannot_borrow"] is True
    makerspace.refresh_from_db()
    assert makerspace.lapsed_members_cannot_borrow is True
    assert AuditLog.objects.filter(action="makerspace.updated", makerspace=makerspace).exists()
