from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import PasswordResetEnvelope, PasswordResetEnvelopeStatus, User
from apps.accounts.password_reset_crypto import otp_digest
from apps.accounts.services_password_reset import (
    GENERIC_CONFIRM_ERROR,
    PasswordResetCooldown,
    confirm_password_reset,
    request_password_reset,
)
from apps.accounts.services_password_reset_drain import (
    CLAIM_LEASE,
    claim_pending_envelopes,
    discard_expired_issued,
    expire_delivery_leases,
    finalize_delivery,
    prepare_delivery,
)

pytestmark = pytest.mark.django_db

EMAIL = "member@example.org"
NOW = timezone.now()
STRONG_PASSWORD = "Correct-horse-battery-staple-419!"


def member(**changes):
    values = {
        "email": EMAIL,
        "password": "starting-password-419!",
        "role": User.Role.REQUESTER,
    }
    values.update(changes)
    return User.objects.create_user(username="reset-member", **values)


def claim(email=EMAIL, *, now=NOW):
    request_password_reset(email, now=now)
    return claim_pending_envelopes(owner="test-worker", now=now)[0]


def test_request_path_never_queries_accounts_or_issues_a_live_digest():
    with CaptureQueriesContext(connection) as captured:
        envelope = request_password_reset("unknown@example.org", now=NOW)

    assert not any('"accounts_user"' in query["sql"] for query in captured.captured_queries)
    assert envelope.status == PasswordResetEnvelopeStatus.PENDING
    assert envelope.user_id is None
    assert envelope.digest_is_live is False
    assert envelope.expires_at is None


def test_complete_happy_path_moves_pending_through_consumed(monkeypatch):
    user = member()
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )

    envelope = request_password_reset(" Member@Example.ORG ", now=NOW)
    assert envelope.status == PasswordResetEnvelopeStatus.PENDING
    assert envelope.generation == 1
    first_dummy = envelope.digest

    envelope_claim = claim_pending_envelopes(owner="worker-a", now=NOW)[0]
    assert envelope_claim.generation == 2
    attempt = prepare_delivery(envelope_claim, now=NOW)
    envelope.refresh_from_db()
    assert envelope.status == PasswordResetEnvelopeStatus.DELIVERING
    assert envelope.digest_is_live is True
    assert envelope.digest != first_dummy
    assert envelope.user_id == user.pk

    assert finalize_delivery(envelope_claim, delivered=True, now=NOW) is True
    envelope.refresh_from_db()
    assert envelope.status == PasswordResetEnvelopeStatus.ISSUED
    assert envelope.claim_owner == ""

    confirmed = confirm_password_reset(
        EMAIL, attempt.code, STRONG_PASSWORD, now=NOW + timedelta(seconds=1)
    )
    envelope.refresh_from_db()
    user.refresh_from_db()
    assert confirmed.pk == user.pk
    assert user.check_password(STRONG_PASSWORD)
    assert envelope.status == PasswordResetEnvelopeStatus.CONSUMED
    assert envelope.consumed_at is not None
    assert envelope.terminal_at is not None
    assert envelope.digest_is_live is False

    with pytest.raises(serializers.ValidationError):
        confirm_password_reset(
            EMAIL, attempt.code, "Another-valid-password-880!", now=NOW
        )
    user.refresh_from_db()
    assert user.check_password(STRONG_PASSWORD)


@pytest.mark.parametrize(
    "status",
    [
        PasswordResetEnvelopeStatus.ISSUED,
        PasswordResetEnvelopeStatus.CONSUMED,
        PasswordResetEnvelopeStatus.DISCARDED,
        PasswordResetEnvelopeStatus.UNDELIVERABLE,
        PasswordResetEnvelopeStatus.DELIVERY_UNKNOWN,
    ],
)
def test_every_reentrant_state_resets_exactly(status):
    envelope = request_password_reset(EMAIL, now=NOW - timedelta(minutes=5))
    old_digest = envelope.digest
    PasswordResetEnvelope.objects.filter(pk=envelope.pk).update(
        digest="f" * 64,
        digest_is_live=True,
        credential_fingerprint="c" * 64,
        user=member(),
        expires_at=NOW,
        consumed_at=NOW,
        attempts=4,
        status=status,
        claimed_at=NOW,
        claim_owner="old-worker",
        claim_expires_at=NOW,
        generation=9,
        superseded_at=NOW,
        terminal_at=NOW,
    )

    request_password_reset(EMAIL, now=NOW)
    envelope.refresh_from_db()

    assert envelope.status == PasswordResetEnvelopeStatus.PENDING
    assert envelope.digest not in {old_digest, "f" * 64}
    assert envelope.digest_is_live is False
    assert envelope.credential_fingerprint == ""
    assert envelope.user_id is None
    assert envelope.expires_at is None
    assert envelope.consumed_at is None
    assert envelope.attempts == 0
    assert envelope.claimed_at is None
    assert envelope.claim_owner == ""
    assert envelope.claim_expires_at is None
    assert envelope.generation == 10
    assert envelope.requested_at == NOW
    assert envelope.superseded_at is None
    assert envelope.terminal_at is None


@pytest.mark.parametrize(
    "status",
    [PasswordResetEnvelopeStatus.CLAIMED, PasswordResetEnvelopeStatus.DELIVERING],
)
def test_request_during_claim_or_delivery_is_a_complete_noop(status):
    envelope = request_password_reset(EMAIL, now=NOW - timedelta(minutes=5))
    PasswordResetEnvelope.objects.filter(pk=envelope.pk).update(
        status=status,
        generation=8,
        claimed_at=NOW,
        claim_owner="worker",
        claim_expires_at=NOW + timedelta(minutes=2),
    )
    before = PasswordResetEnvelope.objects.values().get(pk=envelope.pk)

    request_password_reset(EMAIL, now=NOW)

    after = PasswordResetEnvelope.objects.values().get(pk=envelope.pk)
    assert after == before


def test_reentrant_request_honors_cooldown_without_mutating_state():
    envelope = request_password_reset(EMAIL, now=NOW)
    PasswordResetEnvelope.objects.filter(pk=envelope.pk).update(
        status=PasswordResetEnvelopeStatus.ISSUED
    )
    with pytest.raises(PasswordResetCooldown):
        request_password_reset(EMAIL, now=NOW + timedelta(seconds=30))
    envelope.refresh_from_db()
    assert envelope.status == PasswordResetEnvelopeStatus.ISSUED
    assert envelope.generation == 1


def test_expired_claim_is_reclaimed_and_fences_the_old_worker(monkeypatch):
    member()
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    old_claim = claim(now=NOW)
    new_claim = claim_pending_envelopes(
        owner="new-worker", now=NOW + CLAIM_LEASE + timedelta(seconds=1)
    )[0]

    assert new_claim.generation == old_claim.generation + 1
    assert prepare_delivery(old_claim, now=NOW) is None
    assert prepare_delivery(new_claim, now=NOW) is not None


def test_expired_delivering_becomes_terminal_and_fences_finalization(monkeypatch):
    member()
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    envelope_claim = claim(now=NOW)
    prepare_delivery(envelope_claim, now=NOW)
    envelope = PasswordResetEnvelope.objects.get(pk=envelope_claim.envelope_id)
    live_digest = envelope.digest

    changed = expire_delivery_leases(
        now=NOW + CLAIM_LEASE + timedelta(seconds=1)
    )
    envelope.refresh_from_db()

    assert changed == 1
    assert envelope.status == PasswordResetEnvelopeStatus.DELIVERY_UNKNOWN
    assert envelope.generation == envelope_claim.generation + 1
    assert envelope.digest != live_digest
    assert envelope.digest_is_live is False
    assert envelope.terminal_at is not None
    assert finalize_delivery(envelope_claim, delivered=True, now=NOW) is False
    envelope.refresh_from_db()
    assert envelope.status == PasswordResetEnvelopeStatus.DELIVERY_UNKNOWN


def test_current_password_change_invalidates_a_correct_code(monkeypatch):
    user = member()
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    envelope_claim = claim(now=NOW)
    attempt = prepare_delivery(envelope_claim, now=NOW)
    finalize_delivery(envelope_claim, delivered=True, now=NOW)
    user.set_password("newer-credential-771!")
    user.save(update_fields=["password"])

    with pytest.raises(serializers.ValidationError) as exc:
        confirm_password_reset(EMAIL, attempt.code, STRONG_PASSWORD, now=NOW)

    assert exc.value.detail["detail"] == GENERIC_CONFIRM_ERROR
    envelope = PasswordResetEnvelope.objects.get(pk=envelope_claim.envelope_id)
    assert envelope.status == PasswordResetEnvelopeStatus.DISCARDED
    assert envelope.digest_is_live is False


def test_expired_issued_code_is_discarded_and_cleared(monkeypatch):
    member()
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    envelope_claim = claim(now=NOW)
    prepare_delivery(envelope_claim, now=NOW)
    finalize_delivery(envelope_claim, delivered=True, now=NOW)
    envelope = PasswordResetEnvelope.objects.get(pk=envelope_claim.envelope_id)
    live_digest = envelope.digest

    assert discard_expired_issued(now=envelope.expires_at + timedelta(seconds=1)) == 1
    envelope.refresh_from_db()
    assert envelope.status == PasswordResetEnvelopeStatus.DISCARDED
    assert envelope.digest != live_digest
    assert envelope.digest_is_live is False
    assert envelope.terminal_at is not None


def test_wrong_codes_hit_the_low_attempt_cap_and_become_terminal(monkeypatch):
    member()
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    envelope_claim = claim(now=NOW)
    attempt = prepare_delivery(envelope_claim, now=NOW)
    finalize_delivery(envelope_claim, delivered=True, now=NOW)
    wrong_code = "000000" if attempt.code != "000000" else "000001"

    for _ in range(5):
        with pytest.raises(serializers.ValidationError):
            confirm_password_reset(EMAIL, wrong_code, STRONG_PASSWORD, now=NOW)

    envelope = PasswordResetEnvelope.objects.get(pk=envelope_claim.envelope_id)
    assert envelope.attempts == 5
    assert envelope.status == PasswordResetEnvelopeStatus.ISSUED
    assert discard_expired_issued(now=NOW) == 1
    envelope.refresh_from_db()
    assert envelope.status == PasswordResetEnvelopeStatus.DISCARDED
    assert envelope.digest_is_live is False


def test_digest_is_domain_separated_by_email():
    assert otp_digest("123456", EMAIL) != otp_digest("123456", "other@example.org")
