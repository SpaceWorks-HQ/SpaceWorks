"""Opaque, expiring first-factor proofs; no JWT exists until the second factor succeeds."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from apps.accounts import audit_events
from apps.accounts.mfa_crypto import new_secret, provisioning_uri
from apps.accounts.mfa_policy import stamp
from apps.accounts.models import User
from apps.accounts.models_mfa import MFAChallenge, UserMFA
from apps.accounts.password_reset_crypto import credential_fingerprint
from apps.accounts.services_mfa import active, consume_code, enable
from apps.accounts.tokens import current_auth_generation
from apps.makerspaces.secrets import decrypt_value, encrypt_value


def digest(raw):
    return hashlib.sha256(str(raw).encode()).hexdigest()


@transaction.atomic
def start(user, *, context):
    user = User.objects.select_for_update().get(pk=user.pk)
    active(user)
    row, _ = UserMFA.objects.get_or_create(user=user)
    raw = secrets.token_urlsafe(32)
    challenge = MFAChallenge.objects.create(
        user=user, token_digest=digest(raw), mfa_version=row.version,
        credential_fingerprint=credential_fingerprint(user, user.email),
        auth_generation=current_auth_generation(), context=context,
        expires_at=timezone.now() + timedelta(seconds=settings.MFA_CHALLENGE_TTL_SECONDS),
    )
    audit_events.record_auth_event(user, "auth.mfa_challenge_created", target=user)
    return {"mfa_required": True, "enrollment_required": not bool(row.enabled_at),
            "challenge": raw, "expires_in": settings.MFA_CHALLENGE_TTL_SECONDS}


def _locked(raw, request):
    candidate = MFAChallenge.objects.filter(token_digest=digest(raw)).values("pk", "user_id").first()
    if candidate is None:
        raise AuthenticationFailed("Invalid or expired MFA challenge.")
    # Use the same User -> credential -> challenge lock order as management/recovery.
    user = User.objects.select_for_update().get(pk=candidate["user_id"])
    row = UserMFA.objects.select_for_update().get(user=user)
    challenge = MFAChallenge.objects.select_for_update().filter(pk=candidate["pk"]).first()
    if challenge is None:
        raise AuthenticationFailed("Invalid or expired MFA challenge.")
    active(user)
    from apps.accounts.social_nonces import request_origin
    origin = request_origin(request)
    if challenge.context.get("surface") == "control":
        if request.path != "/mfa/control/" or request.user.pk != user.pk:
            raise AuthenticationFailed("Invalid or expired MFA challenge.")
        from urllib.parse import urlsplit
        origin = urlsplit(request.build_absolute_uri("/")).geturl().rstrip("/")
    valid = (challenge.consumed_at is None and challenge.expires_at > timezone.now()
             and challenge.attempts < settings.MFA_MAX_ATTEMPTS
             and challenge.auth_generation == current_auth_generation()
             and challenge.credential_fingerprint == credential_fingerprint(user, user.email)
             and challenge.mfa_version == row.version
             and challenge.context.get("origin", "") == origin)
    if not valid:
        raise AuthenticationFailed("Invalid or expired MFA challenge.")
    return challenge, user, row


@transaction.atomic
def enroll(raw, request):
    challenge, user, row = _locked(raw, request)
    if row.enabled_at:
        raise AuthenticationFailed("MFA is already enrolled.")
    if not challenge.pending_secret:
        challenge.pending_secret = encrypt_value(new_secret())
        challenge.save(update_fields=["pending_secret"])
        audit_events.record_auth_event(user, "auth.mfa_enrollment_started", target=user)
    secret = decrypt_value(challenge.pending_secret)
    uri = provisioning_uri(secret, user.username)
    import base64
    import io
    import segno
    output = io.BytesIO()
    segno.make(uri, micro=False).save(output, kind="png", scale=5)
    return {"secret": secret, "provisioning_uri": uri,
            "qr_data_url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()}


def finish(raw, code, request, *, enrolling=False):
    refusal = False
    result = None
    with transaction.atomic():
        challenge, user, row = _locked(raw, request)
        codes = None
        if enrolling and not row.enabled_at and challenge.pending_secret:
            codes = enable(user, row, decrypt_value(challenge.pending_secret), code)
            valid = codes is not None
        else:
            valid = bool(not enrolling and row.enabled_at and consume_code(row, code))
        if not valid:
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            audit_events.record_auth_event(user, "auth.mfa_failed", target=user)
            refusal = True
        else:
            stamp(user, row)
            # Context is server-owned; callers cannot widen the login's surface or device.
            from apps.accounts.mfa_sessions import issue_session
            result = issue_session(user, challenge.context, request)
            if codes is not None:
                result["recovery_codes"] = codes
            challenge.consumed_at = timezone.now()
            challenge.pending_secret = ""
            challenge.save(update_fields=["consumed_at", "pending_secret"])
            audit_events.record_auth_event(user, "auth.mfa_verified", target=user)
    if refusal:
        raise AuthenticationFailed("Invalid or expired MFA challenge.")
    return result
