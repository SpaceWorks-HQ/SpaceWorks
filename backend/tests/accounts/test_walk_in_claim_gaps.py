"""Walk-in and claim-code paths the audit found untested (00-audit.md §6).

The phone `confirm_link` walk-in guard was never reached by a test (no valid LINK challenge
was ever built, so `_confirm` failed first); claim codes were never tried against a revoked
membership or another makerspace; two audit entries were never asserted.
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.accounts import services_phone
from apps.accounts.models import MemberClaimCode
from apps.accounts.models_phone import PhoneChallengePurpose, PhoneVerificationChallenge
from apps.audit.models import AuditLog
from apps.makerspaces import membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.walk_in_services import create_walk_in_member
from tests.accounts.claim_helpers_p7 import redeemed_claim
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(name=slug.title(), slug=slug)


def _issue(client, makerspace, membership):
    return client.post(
        f"/api/v1/admin/makerspaces/{makerspace.pk}/member-claim-codes",
        {"membership_id": membership.pk}, format="json",
    )


def _redeem(slug, code):
    return APIClient(REMOTE_ADDR="203.0.113.71").post(
        "/api/v1/auth/claim/redeem", {"makerspace_slug": slug, "code": code}, format="json",
    )


def test_creating_a_walk_in_is_audited_without_contact_details():
    makerspace = _space("gap-walk-in-audit")
    desk = make_handout_member("gap-walk-in-audit-desk", makerspace)

    membership = create_walk_in_member(desk, makerspace, display_name="Counter", phone="555 0100")

    entry = AuditLog.objects.get(action="member.walk_in_created", makerspace=makerspace)
    assert entry.meta == {"has_email": False, "has_phone": True}
    assert "555" not in str(entry.meta)
    assert membership.user.is_walk_in


def test_a_walk_in_holding_a_valid_link_code_is_still_refused_the_phone_and_it_is_audited():
    makerspace = _space("gap-walk-in-phone")
    desk = make_handout_member("gap-walk-in-phone-desk", makerspace)
    walk_in = create_walk_in_member(desk, makerspace, display_name="Walk In").user
    number = "+15550100777"
    challenge = PhoneVerificationChallenge.objects.create(
        user=walk_in, purpose=PhoneChallengePurpose.LINK, phone_e164=number,
        code_digest=services_phone._digest("123456", number),
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    with pytest.raises(ValidationError, match=services_phone.GENERIC_CONFIRM_ERROR):
        services_phone.confirm_link(walk_in, number, "123456")

    walk_in.refresh_from_db()
    assert walk_in.phone_e164 == "" and walk_in.phone_verified_at is None
    challenge.refresh_from_db()
    # The code was consumed before the refusal, so the refusal itself is audited.
    assert challenge.consumed_at is not None
    assert AuditLog.objects.filter(action="member.phone_link_refused_walk_in").exists()


def test_a_claim_code_is_never_issued_for_a_revoked_membership():
    makerspace = _space("gap-claim-revoked-issue")
    desk = make_handout_member("gap-claim-revoked-issue-desk", makerspace)
    membership = create_walk_in_member(desk, makerspace, display_name="Gone")
    MakerspaceMembership.objects.filter(pk=membership.pk).update(status="revoked")
    client = APIClient()
    client.force_authenticate(desk)

    assert _issue(client, makerspace, membership).status_code == 409
    assert not MemberClaimCode.objects.filter(membership=membership).exists()


def test_a_code_issued_before_the_membership_was_revoked_cannot_be_redeemed():
    makerspace = _space("gap-claim-revoked-redeem")
    desk = make_handout_member("gap-claim-revoked-redeem-desk", makerspace)
    membership = create_walk_in_member(desk, makerspace, display_name="Soon Gone")
    client = APIClient()
    client.force_authenticate(desk)
    issued = _issue(client, makerspace, membership)
    assert issued.status_code == 201
    assert AuditLog.objects.filter(action="member.claim_code_issued", makerspace=makerspace).exists()
    MakerspaceMembership.objects.filter(pk=membership.pk).update(status="revoked")

    response = _redeem(makerspace.slug, issued.data["code"])

    assert response.status_code == 400
    entry = AuditLog.objects.filter(action="member.claim_code_redemption_refused").latest("pk")
    assert entry.meta.get("outcome") == "ineligible"


def test_a_code_redeemed_at_another_makerspace_is_refused():
    makerspace, other = _space("gap-claim-home"), _space("gap-claim-elsewhere")
    desk = make_handout_member("gap-claim-home-desk", makerspace)
    membership = create_walk_in_member(desk, makerspace, display_name="Traveller")
    client = APIClient()
    client.force_authenticate(desk)
    issued = _issue(client, makerspace, membership)

    response = _redeem(other.slug, issued.data["code"])

    assert response.status_code == 400
    entry = AuditLog.objects.filter(action="member.claim_code_redemption_refused").latest("pk")
    assert entry.meta.get("outcome") == "wrong_makerspace"


def test_a_live_claim_session_ends_when_the_membership_is_revoked():
    harness = redeemed_claim("gap-live-session")
    url = f"/api/v1/member/makerspaces/{harness.space.pk}/activity"
    assert harness.claim_client.get(url).status_code == 200

    membership_services.revoke_membership(harness.staff, harness.membership, "Left")

    assert harness.claim_client.get(url).status_code == 401


def test_walk_in_marker_blocks_password_change_even_with_a_working_password():
    """A usable password must not make deleting the marker guard invisible to the test."""
    makerspace = _space("gap-walk-in-password")
    desk = make_handout_member("gap-password-desk", makerspace)
    walk_in = create_walk_in_member(desk, makerspace, display_name="Password Guest").user
    walk_in.set_password("Current-pass-3291")
    walk_in.save(update_fields=["password"])
    assert walk_in.check_password("Current-pass-3291")
    client = APIClient(); client.force_authenticate(walk_in)
    response = client.post("/api/v1/auth/change-password", {
        "current_password": "Current-pass-3291", "new_password": "Next-pass-82942",
    }, format="json")
    assert response.status_code == 400
    walk_in.refresh_from_db()
    assert walk_in.check_password("Current-pass-3291")
    assert not AuditLog.objects.filter(action="user.password_changed", actor=walk_in).exists()


def test_phone_confirmation_rereads_walk_in_marker_under_lock():
    from apps.accounts.models import User

    makerspace = _space("gap-phone-stale-user")
    desk = make_handout_member("gap-phone-stale-desk", makerspace)
    walk_in = create_walk_in_member(desk, makerspace, display_name="Stale Guest").user
    walk_in.is_walk_in = False  # The caller holds an old JWT-resolved user object.
    number = "+14155552671"
    PhoneVerificationChallenge.objects.create(
        user=walk_in, purpose=PhoneChallengePurpose.LINK, phone_e164=number,
        code_digest=services_phone._digest("123456", number),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    assert User.objects.get(pk=walk_in.pk).is_walk_in
    with pytest.raises(ValidationError):
        services_phone.confirm_link(walk_in, number, "123456")
    assert AuditLog.objects.filter(action="member.phone_link_refused_walk_in", actor=walk_in).exists()


def test_walk_in_can_unlink_a_preexisting_phone_identity():
    from apps.accounts.models import User

    makerspace = _space("gap-walk-in-unlink")
    desk = make_handout_member("gap-unlink-desk", makerspace)
    walk_in = create_walk_in_member(desk, makerspace, display_name="Unlink Guest").user
    User.objects.filter(pk=walk_in.pk).update(phone_e164="+14155552671", phone_verified_at=timezone.now())
    walk_in.refresh_from_db()
    client = APIClient(); client.force_authenticate(walk_in)
    assert client.delete("/api/v1/auth/phone").status_code == 200
    walk_in.refresh_from_db()
    assert walk_in.phone_e164 == "" and walk_in.phone_verified_at is None
    assert AuditLog.objects.filter(action="member.phone_unlinked", actor=walk_in).exists()


def test_wrong_codes_over_http_accumulate_and_lock_the_code_out():
    # Regression: the refusal used to raise inside tenant_write's transaction, rolling
    # back the failed-attempt counter, so the HTTP brute-force limit never accumulated.
    from apps.accounts.services_claim import MAX_FAILED_ATTEMPTS

    makerspace = _space("gap-claim-bruteforce")
    desk = make_handout_member("gap-claim-bruteforce-desk", makerspace)
    membership = create_walk_in_member(desk, makerspace, display_name="Guessed At")
    client = APIClient()
    client.force_authenticate(desk)
    issued = _issue(client, makerspace, membership)
    assert issued.status_code == 201
    code = issued.data["code"]
    prefix, secret = code[: -len(code.split("-")[-1])], code.split("-")[-1]
    wrong = prefix + ("A" if secret[0] != "A" else "B") + secret[1:]

    for _ in range(MAX_FAILED_ATTEMPTS):
        assert _redeem(makerspace.slug, wrong).status_code == 400

    claim = MemberClaimCode.objects.get(membership=membership)
    assert claim.failed_attempts == MAX_FAILED_ATTEMPTS
    assert claim.consumed_at is not None
    assert AuditLog.objects.filter(action="member.claim_code_redemption_failed").count() == MAX_FAILED_ATTEMPTS
    # The real code no longer works once the guesses exhausted it.
    assert _redeem(makerspace.slug, code).status_code == 400
