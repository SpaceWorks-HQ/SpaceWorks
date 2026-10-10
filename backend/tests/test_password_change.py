from io import StringIO

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.test import Client
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from tests.accounts.mfa_helpers import complete_enrollment, force_mfa_login

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
CHANGE_PASSWORD = "/api/v1/auth/change-password"
AUDIT_LOGS = "/api/v1/admin/audit-logs"


def test_must_change_password_blocks_protected_api_until_rotated():
    """The generated first-run credential must not reach protected staff endpoints over the
    API before rotating — only the rotation/me path stays open."""
    get_user_model().objects.create_user(
        username="gated-superadmin",
        email="gated@example.com",
        password="Current-Strong-123",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
        must_change_password=True,
    )
    client = APIClient()
    login = client.post(
        LOGIN,
        {"username": "gated-superadmin", "password": "Current-Strong-123"},
        format="json",
    )
    if login.data.get("mfa_required"):
        login = complete_enrollment(client, login)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    blocked = client.get(AUDIT_LOGS)
    assert blocked.status_code == 403  # protected surface is closed pre-rotation

    rotated = client.post(
        CHANGE_PASSWORD,
        {"current_password": "Current-Strong-123", "new_password": "New-Strong-123"},
        format="json",
    )
    assert rotated.status_code == 200  # rotation path stayed open

    allowed = client.get(AUDIT_LOGS)
    assert allowed.status_code == 200  # flag cleared, surface reopens


def test_setup_instance_default_superadmin_must_change_password(monkeypatch):
    monkeypatch.delenv("SETUP_SUPERADMIN_USERNAME", raising=False)
    monkeypatch.delenv("SETUP_SUPERADMIN_PASSWORD", raising=False)

    output = StringIO()
    call_command("setup_instance", stdout=output, no_color=True)

    user = get_user_model().objects.get(username="superadmin")
    assert user.must_change_password is True
    password = output.getvalue().split("Generated superadmin password: ", 1)[1].splitlines()[0]
    assert len(password) >= 32
    assert user.check_password(password)
    output = StringIO()
    call_command("setup_instance", stdout=output, no_color=True)
    user.refresh_from_db()
    assert user.check_password(password)
    assert "Generated superadmin password:" not in output.getvalue()


def test_setup_instance_explicit_password_does_not_force_change(monkeypatch):
    monkeypatch.delenv("SETUP_SUPERADMIN_USERNAME", raising=False)
    monkeypatch.delenv("SETUP_SUPERADMIN_PASSWORD", raising=False)

    output = StringIO()
    call_command(
        "setup_instance",
        username="explicit-superadmin",
        password="Explicit-Strong-123",
        stdout=output,
    )

    user = get_user_model().objects.get(username="explicit-superadmin")
    assert user.must_change_password is False
    assert user.check_password("Explicit-Strong-123")
    assert "Explicit-Strong-123" not in output.getvalue()


def test_setup_instance_generates_distinct_credentials(monkeypatch):
    monkeypatch.delenv("SETUP_SUPERADMIN_PASSWORD", raising=False)
    passwords = []
    for username in ("generated-one", "generated-two"):
        output = StringIO()
        call_command("setup_instance", username=username, stdout=output, no_color=True)
        password = output.getvalue().split("Generated superadmin password: ", 1)[1].splitlines()[0]
        passwords.append(password)
        user = get_user_model().objects.get(username=username)
        assert user.check_password(password)
        assert user.must_change_password
    assert passwords[0] != passwords[1]


def test_must_change_password_blocks_django_admin():
    """The generated first-run credential must not reach /admin/ before rotating, or it would
    bypass the API/staff-console forced-change gate."""
    user = get_user_model().objects.create_user(
        username="admin-gated-super",
        email="admin-gated@example.com",
        password="Current-Strong-123",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
        must_change_password=True,
    )
    client = Client()
    client.force_login(user)

    blocked = client.get("/control/")
    assert blocked.status_code == 403

    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    force_mfa_login(client, user)
    assert client.get("/control/").status_code == 200


def test_change_password_blacklists_outstanding_refresh_tokens():
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

    get_user_model().objects.create_user(
        username="rotate-blacklist",
        email="rotate-blacklist@example.com",
        password="Current-Strong-123",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
        must_change_password=True,
    )
    client = APIClient()
    login = client.post(
        LOGIN,
        {"username": "rotate-blacklist", "password": "Current-Strong-123"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    before = BlacklistedToken.objects.count()
    changed = client.post(
        CHANGE_PASSWORD,
        {"current_password": "Current-Strong-123", "new_password": "New-Strong-123"},
        format="json",
    )

    assert changed.status_code == 200
    assert BlacklistedToken.objects.count() > before  # pre-rotation session revoked


def test_login_and_me_include_must_change_password():
    get_user_model().objects.create_user(
        username="must-change",
        email="must-change@example.com",
        password="Current-Strong-123",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
        must_change_password=True,
    )
    client = APIClient()

    login = client.post(
        LOGIN,
        {"username": "must-change", "password": "Current-Strong-123"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    me = client.get(ME)

    assert login.status_code == 200
    assert login.data["user"]["must_change_password"] is True
    assert me.status_code == 200
    assert me.data["must_change_password"] is True


def test_change_password_validates_updates_and_audits():
    user = get_user_model().objects.create_user(
        username="password-user",
        email="password-user@example.com",
        password="Current-Strong-123",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
        must_change_password=True,
    )
    client = APIClient()
    login = client.post(
        LOGIN,
        {"username": "password-user", "password": "Current-Strong-123"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    wrong_current = client.post(
        CHANGE_PASSWORD,
        {"current_password": "wrong", "new_password": "New-Strong-123"},
        format="json",
    )
    equal_password = client.post(
        CHANGE_PASSWORD,
        {
            "current_password": "Current-Strong-123",
            "new_password": "Current-Strong-123",
        },
        format="json",
    )
    weak_password = client.post(
        CHANGE_PASSWORD,
        {"current_password": "Current-Strong-123", "new_password": "short"},
        format="json",
    )
    changed = client.post(
        CHANGE_PASSWORD,
        {"current_password": "Current-Strong-123", "new_password": "New-Strong-123"},
        format="json",
    )

    assert wrong_current.status_code == 400
    assert "current_password" in wrong_current.data
    assert equal_password.status_code == 400
    assert "new_password" in equal_password.data
    assert weak_password.status_code == 400
    assert "new_password" in weak_password.data
    assert changed.status_code == 200
    assert changed.data == {"detail": "Password updated."}

    user.refresh_from_db()
    assert user.must_change_password is False
    assert authenticate(username="password-user", password="New-Strong-123") == user
    assert AuditLog.objects.filter(
        actor=user,
        action="user.password_changed",
        target_type="accounts.user",
        target_id=str(user.id),
    ).exists()
