"""Cryptographic helpers for password-reset envelopes.

Digests are deliberately domain-separated from phone and registration OTPs. The
normalized address is part of the domain because reset confirmation resolves a
challenge by address rather than by user id.
"""

import hashlib
import hmac
import secrets

from django.conf import settings


def normalize_email(value):
    normalized = str(value or "").strip().lower()
    if not normalized or len(normalized) > 254:
        raise ValueError("A valid email address is required.")
    return normalized


def generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_digest(code, email_normalized):
    return _hmac(f"password-reset-otp:v1:{email_normalized}:{code}")


def new_dummy_digest(email_normalized):
    return otp_digest(secrets.token_urlsafe(32), email_normalized)


def fixed_dummy_digest(email_normalized):
    """Constant fallback for a direct confirmation with no preceding request."""
    return _hmac(f"password-reset-missing:v1:{email_normalized}")


def credential_fingerprint(user, email_normalized):
    return _hmac(
        f"password-reset-credential:v1:{email_normalized}:{user.password}"
    )


def _hmac(value):
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
