"""Global member signup and email-verification challenge lifecycle."""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from apps.accounts import audit_events
from apps.accounts.models import EmailVerificationChallenge, User
from apps.integrations.email import send_email_verification_otp
from apps.makerspaces.limits import reserve_platform_otp_quota

logger = logging.getLogger(__name__)
RESEND_COOLDOWN = timedelta(seconds=60)
CHALLENGE_TTL = timedelta(minutes=10)
GENERIC_CONFIRM_ERROR = "Invalid or expired verification code."


class ChallengeCooldown(Exception):
    pass


def _normalize_email(email):
    return email.strip().lower()


def _generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def _digest(code):
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def issue_challenge(user):
    """Persist a fresh challenge and attempt delivery without exposing delivery state."""
    now = timezone.now()
    email = _normalize_email(user.email)
    with transaction.atomic():
        if EmailVerificationChallenge.objects.filter(
            user=user, email=email, last_sent_at__gte=now - RESEND_COOLDOWN
        ).exists():
            raise ChallengeCooldown
        EmailVerificationChallenge.objects.filter(
            user=user,
            email=email,
            consumed_at__isnull=True,
            failed_attempts__lt=5,
            expires_at__gt=now,
        ).update(consumed_at=now)
        code = _generate_otp()
        challenge = EmailVerificationChallenge.objects.create(
            user=user,
            email=email,
            code_digest=_digest(code),
            expires_at=now + CHALLENGE_TTL,
            last_sent_at=now,
        )
        quota_reserved = reserve_platform_otp_quota()
    sent = False
    if quota_reserved:
        try:
            sent = bool(send_email_verification_otp(email, code))
        except Exception:
            logger.exception("email_verification_dispatch_failed")
    audit_events.record_auth_event(
        user,
        "member.email_verification_requested",
        target=user,
        meta={"email_hash": audit_events.fingerprint(email), "email_sent": sent},
    )
    return challenge


def _record_confirm_failure(user, challenge=None):
    meta = {}
    if challenge is not None:
        challenge.failed_attempts += 1
        challenge.save(update_fields=["failed_attempts"])
        meta["email_hash"] = audit_events.fingerprint(challenge.email)
    audit_events.record_auth_event(
        user, "member.email_verification_failed", target=user, meta=meta
    )


def confirm_challenge(user, code):
    now = timezone.now()
    email = _normalize_email(user.email)
    failed = False
    with transaction.atomic():
        # Resolve ONLY the caller's own newest usable challenge for their current email.
        # A foreign user has no matching row, so guessing IDs cannot burn a victim's attempts.
        challenge = (
            EmailVerificationChallenge.objects.select_for_update()
            .filter(
                user=user,
                email=email,
                consumed_at__isnull=True,
                failed_attempts__lt=5,
                expires_at__gt=now,
            )
            .order_by("-created_at")
            .first()
        )
        if challenge is None or not hmac.compare_digest(
            challenge.code_digest, _digest(code)
        ):
            _record_confirm_failure(user, challenge)
            failed = True
        else:
            challenge.consumed_at = now
            challenge.save(update_fields=["consumed_at"])
            User.objects.filter(pk=user.pk, email_verified_at__isnull=True).update(
                email_verified_at=now
            )
            EmailVerificationChallenge.objects.filter(
                user=user, email=challenge.email, consumed_at__isnull=True
            ).update(consumed_at=now)
            user.email_verified_at = now
            audit_events.record_auth_event(
                user,
                "member.email_verified",
                target=user,
                meta={"email_hash": audit_events.fingerprint(challenge.email)},
            )
    if failed:
        raise serializers.ValidationError({"detail": GENERIC_CONFIRM_ERROR})
    return challenge


def register_member(display_name, email, phone, password):
    """Create a global member or quietly resend verification for an existing one."""
    email = _normalize_email(email)
    # Validate the password BEFORE the existence lookup so a weak password always
    # returns the same 400 whether or not the email is already registered — otherwise
    # "weak password" would 400 for new emails but generic-ack for existing ones,
    # leaking account existence (enumeration oracle).
    try:
        validate_password(password)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"password": list(exc.messages)}) from exc
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        try:
            with transaction.atomic():
                user = User(
                    username=f"member_{uuid.uuid4().hex}",
                    display_name=display_name,
                    email=email,
                    phone=phone,
                    role=User.Role.REQUESTER,
                    is_active=True,
                )
                user.set_password(password)
                user.save()
        except IntegrityError:
            user = User.objects.filter(email__iexact=email).first()

    # A walk-in is a person record, not an enrollable account. Silence is required
    # here by the endpoint's account-enumeration contract.
    if user is not None and user.is_walk_in:
        return None

    audit_events.record_auth_event(
        user,
        "member.signup_requested",
        target=user,
        meta={"email_hash": audit_events.fingerprint(email)},
    )
    if user and user.is_active and user.email_verified_at is None:
        try:
            issue_challenge(user)
        except ChallengeCooldown:
            pass
    return user
