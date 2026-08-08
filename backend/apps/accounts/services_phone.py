"""Phone OTP challenge lifecycle: linking a number, and signing in with one.

Modelled on services_registration.py so the two OTP flows behave identically where
they can. The differences are all forced by phone being an *identity* rather than a
contact address, and each is called out where it appears.

Threat model this file is written against -- SIM swap and number recycling are real,
so an SMS code is a weaker factor than a password:

* Phone login is MEMBER SURFACE ONLY. It never mints a staff session. Staff hold
  destructive powers (purge, role grants, inventory writes) and must come through
  password or a social provider from the trusted staff origin.
* A number must be verified through LINK before it can ever be used to sign in, so
  possession has been proven at least once by someone already holding the account.
* The login start endpoint always returns the same generic acknowledgement, so it
  cannot be used to test which numbers have accounts.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.accounts import audit_events
from apps.accounts.models import User
from apps.accounts.models_phone import PhoneChallengePurpose, PhoneVerificationChallenge
from apps.accounts.phone_numbers import normalize_or_none
from apps.integrations.sms import send_sms, sms_configured
from apps.makerspaces.limits import reserve_platform_otp_sms_quota

logger = logging.getLogger(__name__)

RESEND_COOLDOWN = timedelta(seconds=60)
# Shorter than the 10-minute email TTL: a text arrives in seconds, and a code that
# signs someone in deserves a narrower window than one that confirms an address.
CHALLENGE_TTL = timedelta(minutes=5)
MAX_FAILED_ATTEMPTS = 5
GENERIC_CONFIRM_ERROR = "Invalid or expired verification code."
GENERIC_START_ACK = (
    "If that number is registered, a verification code has been sent to it."
)


class ChallengeCooldown(Exception):
    pass


class SmsUnavailable(Exception):
    pass


def _generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def _digest(code, phone_e164):
    """Domain-separate the digest by number.

    The email flow hashes the bare code because it resolves a challenge by user first.
    A login challenge is resolved by NUMBER, so binding the number into the digest
    stops a code issued for one number from ever validating against another.
    """
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"{phone_e164}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _issue(user, phone_e164, purpose):
    """Create a challenge and attempt delivery. Returns (challenge, sent)."""
    now = timezone.now()
    with transaction.atomic():
        if PhoneVerificationChallenge.objects.filter(
            phone_e164=phone_e164,
            purpose=purpose,
            last_sent_at__gte=now - RESEND_COOLDOWN,
        ).exists():
            raise ChallengeCooldown
        # Supersede this number's outstanding challenges for the SAME purpose. Scoping
        # by number rather than by user is what makes the cooldown above meaningful for
        # the login flow, where the caller is anonymous.
        PhoneVerificationChallenge.objects.filter(
            phone_e164=phone_e164,
            purpose=purpose,
            consumed_at__isnull=True,
            failed_attempts__lt=MAX_FAILED_ATTEMPTS,
            expires_at__gt=now,
        ).update(consumed_at=now)
        code = _generate_otp()
        challenge = PhoneVerificationChallenge.objects.create(
            user=user,
            purpose=purpose,
            phone_e164=phone_e164,
            code_digest=_digest(code, phone_e164),
            expires_at=now + CHALLENGE_TTL,
            last_sent_at=now,
        )
        quota_reserved = reserve_platform_otp_sms_quota()
    sent = False
    if quota_reserved:
        # Sent outside the transaction: an HTTP round-trip must not hold a row lock,
        # and the challenge must survive a vendor failure so the generic ack is honest.
        sent = send_sms(
            to=phone_e164,
            body=f"Your {_platform_name()} verification code is {code}. "
            f"It expires in {int(CHALLENGE_TTL.total_seconds() // 60)} minutes.",
        )
    return challenge, sent


def _platform_name():
    return getattr(settings, "ADMIN_SITE_NAME", "Space Works") or "Space Works"


def _confirm(challenge_queryset, code, phone_e164, *, on_failure):
    """Shared confirm: resolve the newest usable challenge and compare in constant time."""
    now = timezone.now()
    challenge = (
        challenge_queryset.select_for_update()
        .filter(
            phone_e164=phone_e164,
            consumed_at__isnull=True,
            failed_attempts__lt=MAX_FAILED_ATTEMPTS,
            expires_at__gt=now,
        )
        .order_by("-created_at")
        .first()
    )
    if challenge is None or not hmac.compare_digest(
        challenge.code_digest, _digest(code, phone_e164)
    ):
        if challenge is not None:
            challenge.failed_attempts += 1
            challenge.save(update_fields=["failed_attempts"])
        on_failure(challenge)
        return None
    challenge.consumed_at = now
    challenge.save(update_fields=["consumed_at"])
    return challenge


def start_link(user, raw_phone):
    """Send a code to a number an authenticated user wants to attach."""
    if not sms_configured():
        raise SmsUnavailable
    phone_e164 = normalize_or_none(raw_phone)
    if phone_e164 is None:
        from apps.accounts.phone_numbers import MESSAGE

        raise serializers.ValidationError({"phone": [MESSAGE]})
    # Deliberately NO pre-send collision check. Answering "that number belongs to someone
    # else" here would make this endpoint a membership oracle: any logged-in member could
    # probe whether a given number is on the platform, which is exactly what the login
    # path is careful never to reveal. The collision is still caught in confirm_link,
    # under the row lock, so nothing can be taken over -- the attacker simply learns
    # nothing. Cost accepted: the real owner may receive one unsolicited code per probe,
    # bounded by the 5/hour per-number throttle.
    challenge, sent = _issue(user, phone_e164, PhoneChallengePurpose.LINK)
    audit_events.record_auth_event(
        user,
        "member.phone_link_requested",
        target=user,
        meta={
            "phone_hash": audit_events.fingerprint(phone_e164),
            "sms_sent": sent,
        },
    )
    return challenge


def confirm_link(user, raw_phone, code):
    """Attach the number to the caller's account once the code checks out."""
    phone_e164 = normalize_or_none(raw_phone)
    if phone_e164 is None:
        raise serializers.ValidationError({"detail": GENERIC_CONFIRM_ERROR})
    now = timezone.now()
    # Errors are collected and raised AFTER the transaction commits. Raising inside it
    # rolls back the failed_attempts increment along with everything else, which
    # silently disables the attempt cap -- the counter can never rise past zero and a
    # code becomes guessable indefinitely. Same reason services_registration defers.
    failure = None
    with transaction.atomic():
        challenge = _confirm(
            PhoneVerificationChallenge.objects.filter(
                user=user, purpose=PhoneChallengePurpose.LINK
            ),
            code,
            phone_e164,
            on_failure=lambda row: audit_events.record_auth_event(
                user, "member.phone_link_failed", target=user, meta={}
            ),
        )
        if challenge is None:
            failure = {"detail": GENERIC_CONFIRM_ERROR}
        # Re-check the collision under the transaction. start_link's check is a courtesy
        # to avoid a pointless text; THIS is the one that closes the race where two
        # accounts confirm the same number concurrently. The unique index is the final
        # backstop, but a caught IntegrityError would surface as a 500. The lock must be
        # held until the write below, so this stays in the same transaction.
        elif (
            User.objects.select_for_update()
            .filter(phone_e164=phone_e164, phone_verified_at__isnull=False)
            .exclude(pk=user.pk)
            .exists()
        ):
            failure = {"phone": ["That number is already linked to another account."]}
        else:
            user.phone_e164 = phone_e164
            # Populate the free-text contact field only when the member has none, so
            # linking never overwrites a number they typed for staff to call.
            update_fields = ["phone_e164"]
            if not user.phone:
                user.phone = phone_e164
                update_fields.append("phone")
            user.save(update_fields=update_fields)
            # Stamp verification through the queryset, NOT through save(). The model hook
            # clears phone_verified_at whenever phone_e164 changes -- unconditionally,
            # and that is the point: it stops an edited number from inheriting someone
            # else's verified status. So the stamp is written after, bypassing save().
            # Exactly what confirm_challenge does for email_verified_at.
            User.objects.filter(pk=user.pk).update(phone_verified_at=now)
            user.phone_verified_at = now
            audit_events.record_auth_event(
                user,
                "member.phone_verified",
                target=user,
                meta={"phone_hash": audit_events.fingerprint(phone_e164)},
            )
    if failure is not None:
        raise serializers.ValidationError(failure)
    return user


def start_login(raw_phone):
    """Send a login code, revealing nothing about whether the number is known.

    Returns None in every non-send case. The caller must respond with the same
    generic acknowledgement regardless, or this becomes a number-enumeration oracle.
    """
    if not sms_configured():
        raise SmsUnavailable
    phone_e164 = normalize_or_none(raw_phone)
    if phone_e164 is None:
        return None
    user = User.objects.filter(
        phone_e164=phone_e164,
        phone_verified_at__isnull=False,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
    ).first()
    if user is None:
        # No row, no text, no audit against a user that may not exist -- and crucially
        # no distinguishable response. A restricted/suspended account lands here too,
        # so its status is not observable from outside either.
        return None
    try:
        challenge, sent = _issue(user, phone_e164, PhoneChallengePurpose.LOGIN)
    except ChallengeCooldown:
        # Swallowed on purpose. Surfacing a 429 only for known numbers would leak
        # exactly what the generic ack is protecting.
        return None
    audit_events.record_auth_event(
        user,
        "auth.phone_login_requested",
        target=user,
        meta={"phone_hash": audit_events.fingerprint(phone_e164), "sms_sent": sent},
    )
    return challenge


def confirm_login(raw_phone, code):
    """Resolve the member behind a valid login code, or raise a generic 400."""
    phone_e164 = normalize_or_none(raw_phone)
    if phone_e164 is None:
        raise serializers.ValidationError({"detail": GENERIC_CONFIRM_ERROR})
    # Deferred raise, for the same reason as confirm_link: a rollback would undo the
    # failed_attempts increment and leave the per-challenge attempt cap inert.
    user = None
    with transaction.atomic():
        challenge = _confirm(
            PhoneVerificationChallenge.objects.filter(
                purpose=PhoneChallengePurpose.LOGIN
            ),
            code,
            phone_e164,
            on_failure=lambda row: audit_events.record_auth_event(
                getattr(row, "user", None),
                "auth.phone_login_failed",
                meta={"phone_hash": audit_events.fingerprint(phone_e164)},
            ),
        )
        if challenge is not None:
            # Re-read the user under the lock and re-assert every gate start_login
            # checked. A member suspended in the 5 minutes between request and confirm
            # must not get a session, and the challenge row alone cannot tell us that.
            user = (
                User.objects.select_for_update()
                .filter(
                    pk=challenge.user_id,
                    phone_e164=phone_e164,
                    phone_verified_at__isnull=False,
                    is_active=True,
                    access_status=User.AccessStatus.ACTIVE,
                )
                .first()
            )
    if user is None:
        raise serializers.ValidationError({"detail": GENERIC_CONFIRM_ERROR})
    return user
