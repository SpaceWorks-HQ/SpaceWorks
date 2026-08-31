"""Request and confirmation services for the password-reset envelope."""

import hmac
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from apps.accounts import audit_events
from apps.accounts.models import PasswordResetEnvelope, PasswordResetEnvelopeStatus, User
from apps.accounts.principal_guards import is_anonymous_requester
from apps.accounts.password_reset_crypto import (
    credential_fingerprint,
    fixed_dummy_digest,
    new_dummy_digest,
    normalize_email,
    otp_digest,
)
from apps.accounts.services_tokens import blacklist_outstanding_tokens

RESEND_COOLDOWN = timedelta(seconds=60)
MAX_ATTEMPTS = 5
GENERIC_CONFIRM_ERROR = "Invalid or expired verification code."

REENTRANT_STATUSES = frozenset(
    {
        PasswordResetEnvelopeStatus.ISSUED,
        PasswordResetEnvelopeStatus.CONSUMED,
        PasswordResetEnvelopeStatus.DISCARDED,
        PasswordResetEnvelopeStatus.UNDELIVERABLE,
        PasswordResetEnvelopeStatus.DELIVERY_UNKNOWN,
    }
)
BLOCKED_STATUSES = frozenset(
    {
        PasswordResetEnvelopeStatus.PENDING,
        PasswordResetEnvelopeStatus.CLAIMED,
        PasswordResetEnvelopeStatus.DELIVERING,
    }
)


class PasswordResetCooldown(Exception):
    pass


def request_password_reset(email, *, now=None):
    """Upsert the anonymous queue envelope without resolving an account.

    A request already pending, claimed, or delivering is deliberately a no-op. In
    particular, generation fencing cannot un-send mail, so delivery owns the row until
    its SMTP outcome is known or its lease becomes ``delivery_unknown``.
    """
    normalized = normalize_email(email)
    requested_at = now or timezone.now()
    cooled_down = False
    with transaction.atomic():
        envelope, created = _lock_or_create(normalized, requested_at)
        if not created and envelope.status in REENTRANT_STATUSES:
            if envelope.requested_at > requested_at - RESEND_COOLDOWN:
                cooled_down = True
            else:
                _reenter_pending(envelope, normalized, requested_at)
        elif not created and envelope.status not in BLOCKED_STATUSES:
            # Fail closed if a future state is added without defining its resend rule.
            cooled_down = True
        audit_events.record_auth_event(
            None,
            "auth.password_reset_requested",
            target=envelope,
            meta={
                "email_hash": audit_events.fingerprint(normalized),
                "method": "otp",
            },
        )
    if cooled_down:
        raise PasswordResetCooldown
    return envelope


def _lock_or_create(normalized, requested_at):
    envelope = (
        PasswordResetEnvelope.objects.select_for_update()
        .filter(email_normalized__iexact=normalized)
        .first()
    )
    if envelope is not None:
        return envelope, False
    try:
        # The savepoint is important: a concurrent first insert may win the functional
        # unique constraint. Rolling back only this savepoint keeps the outer transaction
        # usable so it can lock the winner.
        with transaction.atomic():
            envelope = PasswordResetEnvelope.objects.create(
                email_normalized=normalized,
                email_fingerprint=audit_events.fingerprint(normalized),
                digest=new_dummy_digest(normalized),
                digest_is_live=False,
                generation=1,
                requested_at=requested_at,
            )
        return envelope, True
    except IntegrityError:
        envelope = PasswordResetEnvelope.objects.select_for_update().get(
            email_normalized__iexact=normalized
        )
        return envelope, False


def _reenter_pending(envelope, normalized, requested_at):
    envelope.email_normalized = normalized
    envelope.email_fingerprint = audit_events.fingerprint(normalized)
    envelope.digest = new_dummy_digest(normalized)
    envelope.digest_is_live = False
    envelope.credential_fingerprint = ""
    envelope.user = None
    envelope.expires_at = None
    envelope.consumed_at = None
    envelope.attempts = 0
    envelope.status = PasswordResetEnvelopeStatus.PENDING
    envelope.claimed_at = None
    envelope.claim_owner = ""
    envelope.claim_expires_at = None
    envelope.generation += 1
    envelope.requested_at = requested_at
    envelope.superseded_at = None
    envelope.terminal_at = None
    envelope.save()


def confirm_password_reset(email, code, new_password, *, now=None):
    """Consume a live OTP and rotate the bound account credential.

    The envelope is locked and compared before any user lookup. All errors whose
    counters or terminal state must persist are raised only after the atomic block.
    """
    normalized = normalize_email(email)
    confirmed_at = now or timezone.now()
    failure = {"detail": GENERIC_CONFIRM_ERROR}
    password_failure = None
    confirmed_user = None

    with transaction.atomic():
        envelope = (
            PasswordResetEnvelope.objects.select_for_update()
            .filter(email_normalized__iexact=normalized)
            .first()
        )
        stored_digest = (
            envelope.digest if envelope is not None else fixed_dummy_digest(normalized)
        )
        # Nothing may branch on digest_is_live until this constant-time comparison has
        # happened. Unknown and non-live rows therefore pay the same cryptographic work.
        digest_matches = hmac.compare_digest(
            stored_digest, otp_digest(str(code), normalized)
        )
        attempts_before = envelope.attempts if envelope is not None else MAX_ATTEMPTS
        if envelope is not None:
            envelope.attempts = min(envelope.attempts + 1, MAX_ATTEMPTS)
            envelope.save(update_fields=["attempts"])
        audit_events.record_auth_event(
            None,
            "auth.password_reset_confirm_attempted",
            target=envelope,
            meta={"method": "otp"},
        )

        stage_one_passes = bool(
            envelope is not None
            and digest_matches
            and envelope.digest_is_live
            and envelope.status == PasswordResetEnvelopeStatus.ISSUED
            and envelope.consumed_at is None
            and envelope.expires_at is not None
            and envelope.expires_at > confirmed_at
            and attempts_before < MAX_ATTEMPTS
        )
        if stage_one_passes:
            user = User.objects.select_for_update().filter(pk=envelope.user_id).first()
            if not _credential_state_matches(user, envelope, normalized):
                _discard_locked(envelope, confirmed_at, superseded=True)
            else:
                try:
                    validate_recovery_password(new_password, user)
                except DjangoValidationError as exc:
                    password_failure = {"new_password": list(exc.messages)}
                else:
                    user.set_password(new_password)
                    user.must_change_password = False
                    user.save(update_fields=["password", "must_change_password"])
                    envelope.status = PasswordResetEnvelopeStatus.CONSUMED
                    envelope.consumed_at = confirmed_at
                    envelope.terminal_at = confirmed_at
                    envelope.digest = new_dummy_digest(normalized)
                    envelope.digest_is_live = False
                    envelope.save(
                        update_fields=[
                            "status",
                            "consumed_at",
                            "terminal_at",
                            "digest",
                            "digest_is_live",
                        ]
                    )
                    audit_events.record_auth_event(
                        user,
                        "user.password_reset_via_email",
                        target=user,
                        meta={"method": "otp"},
                    )
                    confirmed_user = user

    if password_failure is not None:
        raise serializers.ValidationError(password_failure)
    if confirmed_user is None:
        raise serializers.ValidationError(failure)
    blacklist_outstanding_tokens(confirmed_user)
    return confirmed_user


def _credential_state_matches(user, envelope, normalized):
    if user is None:
        return False
    try:
        current_email = normalize_email(user.email)
    except ValueError:
        return False
    return bool(
        not user.is_tenant_dump_stub
        and user.is_active
        and user.access_status == User.AccessStatus.ACTIVE
        and not user.is_walk_in
        and not is_anonymous_requester(user)
        and current_email == normalized
        and hmac.compare_digest(
            envelope.credential_fingerprint,
            credential_fingerprint(user, normalized),
        )
    )


def validate_recovery_password(new_password, user):
    """Run candidate-password checks only after the caller has proved possession."""
    if not new_password:
        raise DjangoValidationError("This password may not be blank.")
    validate_password(new_password, user=user)


def _discard_locked(envelope, now, *, superseded=False):
    envelope.status = PasswordResetEnvelopeStatus.DISCARDED
    envelope.digest = new_dummy_digest(envelope.email_normalized)
    envelope.digest_is_live = False
    envelope.credential_fingerprint = ""
    envelope.expires_at = None
    envelope.terminal_at = now
    if superseded:
        envelope.superseded_at = now
    envelope.save(
        update_fields=[
            "status",
            "digest",
            "digest_is_live",
            "credential_fingerprint",
            "expires_at",
            "terminal_at",
            "superseded_at",
        ]
    )
