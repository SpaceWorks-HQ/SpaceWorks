"""Anonymous phone-login half of the OTP service."""

from django.db import transaction
from rest_framework import serializers

from apps.accounts import audit_events
from apps.accounts.models import User
from apps.accounts.models_phone import PhoneChallengePurpose, PhoneVerificationChallenge
from apps.accounts.phone_numbers import normalize_or_none
from apps.integrations.sms import sms_configured

from .services_phone import (
    ChallengeCooldown,
    GENERIC_CONFIRM_ERROR,
    SmsUnavailable,
    _confirm,
    _issue,
)


def start_login(raw_phone):
    """Send a login code without revealing whether the number is known."""
    if not sms_configured():
        raise SmsUnavailable
    phone_e164 = normalize_or_none(raw_phone)
    if phone_e164 is None:
        return None
    user = User.objects.filter(
        phone_e164=phone_e164,
        phone_verified_at__isnull=False,
        is_tenant_dump_stub=False,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
    ).first()
    if user is None:
        return None
    try:
        challenge, sent = _issue(user, phone_e164, PhoneChallengePurpose.LOGIN)
    except ChallengeCooldown:
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
            user = (
                User.objects.select_for_update()
                .filter(
                    pk=challenge.user_id,
                    phone_e164=phone_e164,
                    phone_verified_at__isnull=False,
                    is_tenant_dump_stub=False,
                    is_active=True,
                    access_status=User.AccessStatus.ACTIVE,
                )
                .first()
            )
    if user is None:
        raise serializers.ValidationError({"detail": GENERIC_CONFIRM_ERROR})
    return user
