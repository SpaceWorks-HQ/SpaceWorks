"""Explicit verified-session fixtures for tests that exercise unrelated admin behavior."""

from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone

from apps.accounts.mfa_crypto import new_secret, totp
from apps.accounts.models_mfa import UserMFA
from apps.makerspaces.secrets import encrypt_value

_TEST_KEY = Fernet.generate_key().decode()


def enrolled(user, *, secret=None, recovery_digests=None):
    if not settings.API_CLIENT_ENC_KEY:
        settings.API_CLIENT_ENC_KEY = _TEST_KEY
    secret = secret or new_secret()
    row, _ = UserMFA.objects.update_or_create(user=user, defaults={
        "secret": encrypt_value(secret), "enabled_at": timezone.now(), "last_step": -1,
        "recovery_digests": recovery_digests or [],
    })
    return row, secret


def force_mfa_login(client, user):
    """Model an already verified control session; never bypass production permissions."""
    client.force_login(user)
    if user.is_superuser:
        row, _ = enrolled(user)
        session = client.session
        session["mfa_version"] = str(row.version)
        session.save()


def complete_enrollment(client, response, **headers):
    """Exercise the real API enrollment after a first-factor login."""
    if not settings.API_CLIENT_ENC_KEY:
        settings.API_CLIENT_ENC_KEY = _TEST_KEY
    raw = response.data["challenge"]
    setup = client.post("/api/v1/auth/mfa/enroll", {"challenge": raw}, format="json", **headers)
    assert setup.status_code == 200
    code = totp(setup.data["secret"], int(timezone.now().timestamp() // 30))
    result = client.post("/api/v1/auth/mfa/confirm", {"challenge": raw, "code": code}, format="json", **headers)
    assert result.status_code == 200
    return result
