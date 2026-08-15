"""Retention for spent auth challenges.

The safety property under test is the one that matters: a live challenge is never deleted,
however old the cutoff, so this task can never invalidate a code a member is using.
"""

import pytest
from datetime import timedelta
from django.utils import timezone

from apps.accounts.models import EmailVerificationChallenge, PasswordResetEnvelope, User
from apps.accounts.models_phone import PhoneChallengePurpose, PhoneVerificationChallenge
from apps.accounts.services_challenge_purge import RETENTION, purge_spent_challenges
from tests.return_helpers import make_user

pytestmark = pytest.mark.django_db

OLD = RETENTION + timedelta(days=1)


def user():
    return make_user("purge-subject", role=User.Role.REQUESTER)


def phone_challenge(owner, *, age, **kwargs):
    row = PhoneVerificationChallenge.objects.create(
        user=owner,
        purpose=PhoneChallengePurpose.LOGIN,
        phone_e164="+14155552671",
        code_digest="d" * 64,
        expires_at=timezone.now() + timedelta(minutes=5),
        **kwargs,
    )
    # created_at is auto_now_add, so age it with an update.
    PhoneVerificationChallenge.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - age
    )
    row.refresh_from_db()
    return row


def email_challenge(owner, *, age, **kwargs):
    row = EmailVerificationChallenge.objects.create(
        user=owner,
        email="member@example.org",
        code_digest="d" * 64,
        expires_at=timezone.now() + timedelta(minutes=5),
        **kwargs,
    )
    EmailVerificationChallenge.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - age
    )
    return row


def reset_envelope(*, requested_at, terminal_at=None, status="pending"):
    return PasswordResetEnvelope.objects.create(
        email_normalized="queued@example.org",
        email_fingerprint="f" * 64,
        digest="d" * 64,
        status=status,
        requested_at=requested_at,
        terminal_at=terminal_at,
    )


def test_a_live_challenge_is_never_deleted_however_old():
    """The load-bearing safety property: an unspent code stays redeemable."""
    owner = user()
    phone_challenge(owner, age=OLD)
    email_challenge(owner, age=OLD)
    purge_spent_challenges()
    assert PhoneVerificationChallenge.objects.count() == 1
    assert EmailVerificationChallenge.objects.count() == 1


def test_consumed_rows_past_the_window_go():
    owner = user()
    phone_challenge(owner, age=OLD, consumed_at=timezone.now())
    email_challenge(owner, age=OLD, consumed_at=timezone.now())
    deleted = purge_spent_challenges()
    assert PhoneVerificationChallenge.objects.count() == 0
    assert EmailVerificationChallenge.objects.count() == 0
    assert sum(deleted.values()) == 2


def test_expired_rows_past_the_window_go():
    owner = user()
    row = phone_challenge(owner, age=OLD)
    PhoneVerificationChallenge.objects.filter(pk=row.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    purge_spent_challenges()
    assert PhoneVerificationChallenge.objects.count() == 0


def test_attempt_exhausted_rows_go():
    owner = user()
    phone_challenge(owner, age=OLD, failed_attempts=5)
    purge_spent_challenges()
    assert PhoneVerificationChallenge.objects.count() == 0


def test_a_recently_spent_row_is_kept_for_support():
    """Answering "I never got my code" needs the row to survive a while."""
    owner = user()
    phone_challenge(owner, age=timedelta(days=1), consumed_at=timezone.now())
    purge_spent_challenges()
    assert PhoneVerificationChallenge.objects.count() == 1


def test_both_tables_are_covered_independently():
    """One model failing must not stop the other being cleaned."""
    owner = user()
    phone_challenge(owner, age=OLD, consumed_at=timezone.now())
    email_challenge(owner, age=OLD, consumed_at=timezone.now())
    deleted = purge_spent_challenges()
    assert set(deleted) == {
        "accounts.EmailVerificationChallenge",
        "accounts.PasswordResetEnvelope",
        "accounts.PhoneVerificationChallenge",
    }


def test_stranded_pending_envelope_ages_from_requested_at():
    reset_envelope(requested_at=timezone.now() - OLD)

    purge_spent_challenges()

    assert PasswordResetEnvelope.objects.count() == 0


def test_terminal_envelope_ages_from_terminal_at():
    reset_envelope(
        requested_at=timezone.now(),
        terminal_at=timezone.now() - OLD,
        status="discarded",
    )

    purge_spent_challenges()

    assert PasswordResetEnvelope.objects.count() == 0


def test_recent_terminal_and_live_envelopes_are_retained():
    reset_envelope(
        requested_at=timezone.now() - OLD,
        terminal_at=timezone.now() - timedelta(days=1),
        status="discarded",
    )
    PasswordResetEnvelope.objects.create(
        email_normalized="live@example.org",
        email_fingerprint="a" * 64,
        digest="b" * 64,
        status="issued",
        requested_at=timezone.now(),
        expires_at=timezone.now() + timedelta(minutes=5),
        digest_is_live=True,
    )

    purge_spent_challenges()

    assert PasswordResetEnvelope.objects.count() == 2


def test_the_task_is_registered_on_the_beat_schedule():
    from django.conf import settings

    entry = settings.CELERY_BEAT_SCHEDULE["purge-auth-challenges"]
    assert entry["task"] == "apps.accounts.tasks.purge_auth_challenges_task"
