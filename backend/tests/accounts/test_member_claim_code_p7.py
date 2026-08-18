import json
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import MemberClaimCode, User
from apps.accounts.models_devices import DeviceGrant
from apps.accounts.models_social import SocialIdentity
from apps.accounts.services_claim import (
    ClaimCodeError,
    _digest,
    consume_claim_code,
)
from apps.accounts.transition_services import transition_walk_in_to_account
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db
PASSWORD = "Claim-code test password 947!"


def claim_setup(suffix="base", *, walk_in=True):
    makerspace = Makerspace.objects.create(name=f"Claim {suffix}", slug=f"claim-{suffix}")
    issuer = make_handout_member(f"claim-issuer-{suffix}", makerspace)
    target = User(
        username=f"claim-target-{suffix}",
        display_name=f"Walk In {suffix}",
        is_walk_in=walk_in,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    target.set_unusable_password()
    target.save()
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=target,
        role=MakerspaceMembership.Role.CUSTOM,
    )
    client = APIClient()
    client.force_authenticate(issuer)
    return makerspace, issuer, target, membership, client


def issue(client, makerspace, membership):
    return client.post(
        f"/api/v1/admin/makerspaces/{makerspace.pk}/member-claim-codes",
        {"membership_id": membership.pk},
        format="json",
    )


@pytest.mark.parametrize(
    "state",
    [
        "not_walk_in",
        "password",
        "verified_phone",
        "social_identity",
        "device_grant",
        "telegram",
        "verified_email",
    ],
)
def test_issue_refuses_every_account_or_identity_bearing_state(state):
    makerspace, _, target, membership, client = claim_setup(
        state, walk_in=state != "not_walk_in"
    )
    if state == "password":
        target.set_password(PASSWORD)
        target.save(update_fields=["password"])
    elif state == "verified_phone":
        User.objects.filter(pk=target.pk).update(
            phone_e164="+14155552671", phone_verified_at=timezone.now()
        )
    elif state == "social_identity":
        SocialIdentity.objects.create(
            user=target, provider="google", provider_sub=f"sub-{target.pk}"
        )
    elif state == "device_grant":
        DeviceGrant.objects.create(
            user=target,
            platform="apple",
            app_id="claim.test",
            signing_identity="claim-signing",
            environment="development",
            attestation_subject_fingerprint="d" * 64,
            attested_at=timezone.now(),
            last_used_at=timezone.now(),
        )
    elif state == "telegram":
        target.telegram_user_id = f"telegram-{target.pk}"
        target.save(update_fields=["telegram_user_id"])
    elif state == "verified_email":
        User.objects.filter(pk=target.pk).update(email_verified_at=timezone.now())

    response = issue(client, makerspace, membership)

    assert response.status_code == 409
    assert not MemberClaimCode.objects.filter(membership=membership).exists()


def test_issue_returns_raw_code_once_stores_only_digest_and_never_delivers_it(monkeypatch):
    makerspace, issuer, _, membership, client = claim_setup("one-time")
    email_calls = []
    sms_calls = []
    monkeypatch.setattr(
        "apps.integrations.dispatch.dispatch_email",
        lambda *args, **kwargs: email_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "apps.integrations.sms.send_sms",
        lambda *args, **kwargs: sms_calls.append((args, kwargs)),
    )

    response = issue(client, makerspace, membership)

    assert response.status_code == 201
    raw_code = response.data["code"]
    claim = MemberClaimCode.objects.get(pk=response.data["id"])
    assert raw_code not in claim.code_digest
    assert claim.code_digest == _digest(raw_code)
    assert response.data["qr_svg"].startswith("<svg")
    assert email_calls == []
    assert sms_calls == []
    assert claim.expires_at - claim.issued_at <= timedelta(
        seconds=settings.MEMBER_CLAIM_CODE_TTL_SECONDS + 1
    )

    listed = client.get(
        f"/api/v1/admin/makerspaces/{makerspace.pk}/member-claim-codes"
    )
    assert listed.status_code == 200
    serialized = json.dumps(listed.data)
    assert raw_code not in serialized
    assert claim.code_digest not in serialized
    assert "code_digest" not in serialized
    assert not any(
        raw_code in json.dumps(log.meta) or claim.code_digest in json.dumps(log.meta)
        for log in AuditLog.objects.filter(actor=issuer)
    )


def test_revoke_is_scoped_audited_and_removes_code_from_active_list():
    makerspace, issuer, _, membership, client = claim_setup("revoke")
    created = issue(client, makerspace, membership)
    other_space, _, _, _, _ = claim_setup("revoke-other")

    wrong_tenant = client.post(
        f"/api/v1/admin/makerspaces/{other_space.pk}/member-claim-codes/{created.data['id']}/revoke"
    )
    revoked = client.post(
        f"/api/v1/admin/makerspaces/{makerspace.pk}/member-claim-codes/{created.data['id']}/revoke"
    )

    assert wrong_tenant.status_code in {403, 404}
    assert revoked.status_code == 200
    assert "code" not in revoked.data and "code_digest" not in revoked.data
    claim = MemberClaimCode.objects.get(pk=created.data["id"])
    assert claim.revoked_at is not None and claim.revoked_by == issuer
    assert not client.get(
        f"/api/v1/admin/makerspaces/{makerspace.pk}/member-claim-codes"
    ).data
    assert AuditLog.objects.filter(
        action="member.claim_code_revoked", target_id=str(membership.pk)
    ).exists()


def test_code_is_single_use_and_expiry_refusal_persists_consumption_and_audit():
    makerspace, _, _, membership, client = claim_setup("single")
    created = issue(client, makerspace, membership)
    raw_code = created.data["code"]

    consumed = consume_claim_code(raw_code, redemption_ip="203.0.113.10")
    assert consumed.membership_id == membership.pk
    with pytest.raises(ClaimCodeError):
        consume_claim_code(raw_code, redemption_ip="203.0.113.11")

    expired_setup = claim_setup("expired")
    expired_response = issue(expired_setup[4], expired_setup[0], expired_setup[3])
    expired = MemberClaimCode.objects.get(pk=expired_response.data["id"])
    MemberClaimCode.objects.filter(pk=expired.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(ClaimCodeError):
        consume_claim_code(expired_response.data["code"], redemption_ip="203.0.113.12")
    expired.refresh_from_db()
    assert expired.consumed_at is not None
    refusal = AuditLog.objects.get(
        action="member.claim_code_redemption_refused",
        target_id=str(expired.membership_id),
    )
    assert refusal.meta["redemption_ip"].startswith("hmac-sha256:")
    assert refusal.meta["redemption_ip"] != "203.0.113.12"
    assert refusal.meta["outcome"] == "expired"


def test_failed_attempts_commit_and_cap_the_challenge():
    makerspace, _, _, membership, client = claim_setup("attempts")
    created = issue(client, makerspace, membership)
    prefix = created.data["code"].rsplit("-", 1)[0]
    wrong = f"{prefix}-AAAA"

    for _ in range(5):
        with pytest.raises(ClaimCodeError):
            consume_claim_code(wrong, redemption_ip="203.0.113.20")

    claim = MemberClaimCode.objects.get(pk=created.data["id"])
    assert claim.failed_attempts == 5
    assert claim.consumed_at is not None


def test_transition_service_revokes_unconsumed_codes_through_d2_hook():
    makerspace, issuer, target, membership, client = claim_setup("transition")
    created = issue(client, makerspace, membership)

    transition_walk_in_to_account(target, actor=issuer)

    claim = MemberClaimCode.objects.get(pk=created.data["id"])
    assert claim.consumed_at is None
    assert claim.revoked_at is not None


def test_listing_does_not_spend_issue_budget_and_redeem_has_a_separate_scope(
    settings, monkeypatch
):
    makerspace, _, _, membership, client = claim_setup("budgets")
    cache.clear()
    rest_settings = dict(settings.REST_FRAMEWORK)
    rates = {
        **rest_settings["DEFAULT_THROTTLE_RATES"],
        "member_claim_issue": "1/hour",
        "member_claim_redeem": "20/min",
    }
    rest_settings["DEFAULT_THROTTLE_RATES"] = rates
    settings.REST_FRAMEWORK = rest_settings
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", rates)

    assert client.get(
        f"/api/v1/admin/makerspaces/{makerspace.pk}/member-claim-codes"
    ).status_code == 200
    assert issue(client, makerspace, membership).status_code == 201
    assert issue(client, makerspace, membership).status_code == 429
    assert rates["member_claim_issue"] != rates["member_claim_redeem"]
