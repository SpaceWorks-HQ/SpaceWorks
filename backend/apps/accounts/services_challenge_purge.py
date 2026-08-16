"""Retention for spent auth challenges.

Every sign-in or verification attempt writes a row holding an email address or a phone
number, and nothing deleted them. Volume is modest but unbounded, and the rows are
personal data with no expiry -- the kind of table that is fine for a year and then is not.

Only SPENT rows go: consumed, expired, or attempt-exhausted. A live challenge is never
touched regardless of age, so this can never invalidate a code somebody is mid-way
through using. The window is generous on purpose: "I never got my code" is a real support
question, and answering it needs the row to still exist for a while.
"""

import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=30)
MAX_FAILED_ATTEMPTS = 5


def _spent(now):
    """Rows that can no longer be redeemed, whatever their age."""
    return (
        Q(consumed_at__isnull=False)
        | Q(expires_at__lt=now)
        | Q(failed_attempts__gte=MAX_FAILED_ATTEMPTS)
    )


def purge_spent_challenges(*, retention=RETENTION):
    """Delete spent auth challenges and aged password-reset envelopes.

    Returns a per-model count. Each model is deleted independently so one failure cannot
    prevent the other from being cleaned -- this runs unattended, and a periodic task that
    aborts halfway leaves the operator with no signal beyond a log line.
    """
    from apps.accounts.models import EmailVerificationChallenge
    from apps.accounts.models_phone import PhoneVerificationChallenge
    from apps.accounts.models_password_reset import PasswordResetEnvelope

    now = timezone.now()
    cutoff = now - retention
    deleted = {}
    for model in (EmailVerificationChallenge, PhoneVerificationChallenge):
        label = model._meta.label
        try:
            count, _ = (
                model.objects.filter(_spent(now))
                .filter(created_at__lt=cutoff)
                .delete()
            )
            deleted[label] = count
        except Exception:
            logger.exception("auth_challenge_purge_failed", extra={"model": label})
            deleted[label] = 0

    # PasswordResetEnvelope is an upserted queue row, not an append-only challenge.
    # `requested_at` is therefore its non-terminal age source; `expires_at` may never
    # exist for an attacker-submitted address stranded before issuance.
    label = PasswordResetEnvelope._meta.label
    try:
        count, _ = PasswordResetEnvelope.objects.filter(
            Q(terminal_at__isnull=False, terminal_at__lt=cutoff)
            | Q(terminal_at__isnull=True, requested_at__lt=cutoff)
        ).delete()
        deleted[label] = count
    except Exception:
        logger.exception("auth_challenge_purge_failed", extra={"model": label})
        deleted[label] = 0
    logger.info("auth_challenge_purge_complete", extra={"deleted": deleted})
    return deleted
