import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetEnvelope, PasswordResetEnvelopeStatus, User
from tests.accounts.password_reset_helpers import issue_otp

pytestmark = pytest.mark.django_db


def test_password_validation_failure_commits_the_attempt_before_raising(monkeypatch):
    user = User.objects.create_user(
        username="deferred-password-validation",
        email="deferred-password-validation@example.org",
        password="Starting-password-419!",
        access_status=User.AccessStatus.ACTIVE,
    )
    code = issue_otp(user, monkeypatch)

    response = APIClient().post(
        reverse("auth-reset-password"),
        {"email": user.email, "code": code, "new_password": ""},
        format="json",
    )

    assert response.status_code == 400
    assert "new_password" in response.json()
    envelope = PasswordResetEnvelope.objects.get(user=user)
    assert envelope.attempts == 1
    assert envelope.status == PasswordResetEnvelopeStatus.ISSUED
    assert envelope.consumed_at is None
    user.refresh_from_db()
    assert user.check_password("Starting-password-419!")
