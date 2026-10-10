from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.accounts.mfa_crypto import recovery_codes, totp
from apps.accounts.models import User
from apps.accounts.models_mfa import MFAChallenge, UserMFA
from apps.audit.models import AuditLog
from tests.accounts.mfa_helpers import complete_enrollment, enrolled

pytestmark = pytest.mark.django_db
PASSWORD = "Strong staff password 934!"
LOGIN = "/api/v1/auth/login"
MFA = "/api/v1/auth/mfa"


@pytest.fixture(autouse=True)
def encryption(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()


def owner():
    return User.objects.create_user(username="mfa-owner", email="owner@example.test", password=PASSWORD)


def login(client, user):
    response = client.post(LOGIN, {"username": user.username, "password": PASSWORD,
                                  "surface": "member"}, format="json")
    assert response.status_code == 200
    return response


def verify(client, challenge, code):
    return client.post(MFA + "/verify", {"challenge": challenge, "code": code}, format="json")


def test_password_success_with_mfa_has_no_tokens_until_second_factor():
    user, client = owner(), APIClient()
    row, secret = enrolled(user)
    first = login(client, user)
    assert first.data["mfa_required"] and not first.data["enrollment_required"]
    assert "access" not in first.data and "refresh" not in first.data
    assert not client.cookies.get("refresh_token").value
    assert not OutstandingToken.objects.filter(user=user).exists()
    code = totp(secret, int(timezone.now().timestamp() // 30))
    second = verify(client, first.data["challenge"], code)
    assert second.status_code == 200
    assert second.data["access"] and "refresh" not in second.data
    assert second.cookies["refresh_token"].value
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {second.data['access']}")
    assert client.get("/api/v1/auth/me").status_code == 200
    row.refresh_from_db()
    assert row.last_step >= 0


def test_totp_replay_refused_across_distinct_challenges_and_failure_commits():
    user, client = owner(), APIClient()
    _, secret = enrolled(user)
    one, two = login(client, user).data, login(client, user).data
    code = totp(secret, int(timezone.now().timestamp() // 30))
    assert verify(client, one["challenge"], code).status_code == 200
    assert verify(client, two["challenge"], code).status_code == 401
    assert MFAChallenge.objects.get(consumed_at__isnull=True).attempts == 1
    assert AuditLog.objects.filter(action="auth.mfa_failed").exists()
    assert verify(client, one["challenge"], code).status_code == 401


def test_recovery_code_single_use_and_hashed_storage():
    user, client = owner(), APIClient()
    codes, digests = recovery_codes()
    row, _ = enrolled(user, recovery_digests=digests)
    first, second = login(client, user).data, login(client, user).data
    assert verify(client, first["challenge"], codes[0]).status_code == 200
    assert verify(client, second["challenge"], codes[0]).status_code == 401
    row.refresh_from_db()
    assert len(row.recovery_digests) == 9
    assert not any(check_password(codes[0], value) for value in row.recovery_digests)
    assert AuditLog.objects.filter(action="auth.mfa_recovery_used", actor=user).count() == 1


def test_superadmin_enrollment_encrypts_secret_and_shows_ten_codes_once():
    user = User.objects.create_superuser(username="mfa-root", password=PASSWORD, email="root@example.test")
    client = APIClient()
    first = login(client, user)
    assert first.data["enrollment_required"]
    second = complete_enrollment(client, first)
    codes = second.data["recovery_codes"]
    row = UserMFA.objects.get(user=user)
    assert row.secret.startswith("fernet:")
    assert len(set(codes)) == 10
    assert all(code not in row.recovery_digests for code in codes)
    assert all(check_password(code, digest) for code, digest in zip(codes, row.recovery_digests))
    assert client.post(MFA + "/confirm", {"challenge": first.data["challenge"], "code": codes[0]},
                       format="json").status_code == 401
    next_login = login(client, user)
    assert "recovery_codes" not in verify(client, next_login.data["challenge"], codes[0]).data
    audit = list(AuditLog.objects.filter(action__startswith="auth.mfa").values("meta"))
    assert all(code not in str(audit) for code in codes)


@pytest.mark.parametrize("invalidate", ["expired", "password", "generation", "restricted", "attempts"])
def test_challenge_invalidated_before_token_issuance(invalidate, settings):
    user, client = owner(), APIClient()
    codes, digests = recovery_codes()
    enrolled(user, recovery_digests=digests)
    first = login(client, user)
    row = MFAChallenge.objects.get()
    if invalidate == "expired":
        row.expires_at = timezone.now() - timedelta(seconds=1)
    elif invalidate == "password":
        user.set_password("Replacement password 553!")
        user.save(update_fields=["password"])
    elif invalidate == "generation":
        row.auth_generation = "different-generation"
    elif invalidate == "restricted":
        user.access_status = User.AccessStatus.SUSPENDED
        user.save(update_fields=["access_status"])
    else:
        row.attempts = settings.MFA_MAX_ATTEMPTS
    row.save()
    assert verify(client, first.data["challenge"], codes[0]).status_code == 401
    assert not OutstandingToken.objects.filter(user=user).exists()


def test_regenerate_and_disable_require_password_and_invalidate_old_sessions():
    user, client = owner(), APIClient()
    codes, digests = recovery_codes()
    enrolled(user, recovery_digests=digests)
    response = verify(client, login(client, user).data["challenge"], codes[0])
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert client.post(MFA + "/recovery", {"password": "wrong"}, format="json").status_code == 401
    regenerated = client.post(MFA + "/recovery", {"password": PASSWORD}, format="json")
    assert regenerated.status_code == 200 and len(regenerated.data["recovery_codes"]) == 10
    assert client.get("/api/v1/auth/me").status_code == 401
    client.credentials()
    response = verify(client, login(client, user).data["challenge"], regenerated.data["recovery_codes"][0])
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert client.post(MFA + "/disable", {"password": PASSWORD}, format="json").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    row = UserMFA.objects.get(user=user)
    assert not row.secret and not row.enabled_at and not row.recovery_digests
    client.credentials()
    assert "access" in login(client, user).data


def test_failed_attempts_commit_and_exhaust_challenge(settings):
    user, client = owner(), APIClient()
    codes, digests = recovery_codes()
    enrolled(user, recovery_digests=digests)
    raw = login(client, user).data["challenge"]
    for _ in range(settings.MFA_MAX_ATTEMPTS):
        assert verify(client, raw, "invalid").status_code == 401
    row = MFAChallenge.objects.get()
    assert row.attempts == settings.MFA_MAX_ATTEMPTS
    assert verify(client, raw, codes[0]).status_code == 401
    assert AuditLog.objects.filter(action="auth.mfa_failed").count() == settings.MFA_MAX_ATTEMPTS


def test_spent_mfa_challenges_join_cleanup_but_live_ones_remain():
    from apps.accounts.services_challenge_purge import RETENTION, purge_spent_challenges
    user, client = owner(), APIClient()
    enrolled(user)
    login(client, user)
    old = MFAChallenge.objects.get()
    MFAChallenge.objects.filter(pk=old.pk).update(created_at=timezone.now() - RETENTION - timedelta(days=1))
    purge_spent_challenges()
    assert MFAChallenge.objects.filter(pk=old.pk).exists()
    MFAChallenge.objects.filter(pk=old.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    purge_spent_challenges()
    assert not MFAChallenge.objects.filter(pk=old.pk).exists()
