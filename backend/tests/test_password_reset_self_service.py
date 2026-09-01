import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.models import User
from apps.audit.models import AuditLog
from tests.return_helpers import authenticated_client, make_user

pytestmark = pytest.mark.django_db


def make_superadmin(username):
    return make_user(
        username,
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )


def uid_for(user):
    return urlsafe_base64_encode(force_bytes(user.pk))


@override_settings(
    DEBUG=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)
def test_forgot_password_is_enumeration_safe():
    cache.clear()
    user = make_user(
        "self-reset-existing",
        access_status=User.AccessStatus.ACTIVE,
    )
    url = reverse("auth-forgot-password")

    existing = authenticated_client(user).post(url, {"email": user.email}, format="json")
    missing = authenticated_client(user).post(
        url,
        {"email": "nobody@example.com"},
        format="json",
    )

    assert existing.status_code == 200
    assert missing.status_code == 200
    assert existing.data == missing.data
    events = list(AuditLog.objects.filter(action="auth.password_reset_requested"))
    assert len(events) == 2
    assert user.email not in str([event.meta for event in events])


def test_reset_password_confirm_view_keeps_dedicated_throttle_scope():
    from apps.accounts.views import ResetPasswordConfirmView

    assert ResetPasswordConfirmView.throttle_scope == "password_reset_confirm"


def test_reset_password_confirm_succeeds():
    cache.clear()
    user = make_user(
        "self-reset-confirm",
        access_status=User.AccessStatus.ACTIVE,
        must_change_password=True,
    )
    token = default_token_generator.make_token(user)

    response = authenticated_client(user).post(
        reverse("auth-reset-password"),
        {
            "uid": uid_for(user),
            "token": token,
            "new_password": "NewPass!2345",
        },
        format="json",
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password("NewPass!2345")
    assert user.must_change_password is False


def test_reset_password_confirm_rejects_bad_token():
    cache.clear()
    user = make_user(
        "self-reset-bad-token",
        access_status=User.AccessStatus.ACTIVE,
    )

    response = authenticated_client(user).post(
        reverse("auth-reset-password"),
        {
            "uid": uid_for(user),
            "token": "not-a-real-token",
            "new_password": "NewPass!2345",
        },
        format="json",
    )

    assert response.status_code == 400


def test_reset_password_confirm_rejects_inactive_user():
    cache.clear()
    user = make_user(
        "self-reset-inactive",
        access_status=User.AccessStatus.ACTIVE,
    )
    token = default_token_generator.make_token(user)
    user.access_status = User.AccessStatus.RESTRICTED
    user.save(update_fields=["access_status"])

    response = authenticated_client(user).post(
        reverse("auth-reset-password"),
        {
            "uid": uid_for(user),
            "token": token,
            "new_password": "NewPass!2345",
        },
        format="json",
    )

    assert response.status_code == 400


def test_platform_email_settings_superadmin_only_and_write_only_password(monkeypatch):
    regular = make_user(
        "platform-email-regular",
        access_status=User.AccessStatus.ACTIVE,
    )
    superadmin = make_superadmin("platform-email-super")
    url = reverse("admin-platform-email-settings")
    monkeypatch.setattr(
        "apps.integrations.smtp_validation.socket.getaddrinfo",
        lambda host, port, type=None: [(None, None, None, None, ("8.8.8.8", port))],
    )

    regular_get = authenticated_client(regular).get(url)
    regular_patch = authenticated_client(regular).patch(
        url,
        {"smtp_host": "blocked.example.com"},
        format="json",
    )
    super_client = authenticated_client(superadmin)
    initial = super_client.get(url)
    patched = super_client.patch(
        url,
        {"smtp_host": "smtp.example.com", "smtp_password": "secret"},
        format="json",
    )
    fetched = super_client.get(url)

    assert regular_get.status_code == 403
    assert regular_patch.status_code == 403
    assert initial.status_code == 200
    assert initial.data["smtp_password_set"] is False
    assert patched.status_code == 200
    assert fetched.status_code == 200
    assert fetched.data["smtp_password_set"] is True
    assert fetched.data["smtp_host"] == "smtp.example.com"
    assert "secret" not in str(fetched.data)

