"""`recover_superadmin` (audit gap 10): the privileged host's quarantine break glass."""

import pytest
from io import StringIO
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models import DeploymentRecoveryState

pytestmark = pytest.mark.django_db


def _quarantine():
    DeploymentRecoveryState.objects.update_or_create(
        pk=1,
        defaults={
            "mode": DeploymentRecoveryState.Mode.QUARANTINED,
            "quarantine_reason": "test",
            "quarantined_at": timezone.now(),
        },
    )


def test_refuses_outside_quarantine_and_leaves_the_password_untouched():
    admin = User.objects.create_superuser(username="break-glass", password="original")
    with pytest.raises(CommandError, match="not quarantined"):
        call_command("recover_superadmin", "break-glass")
    admin.refresh_from_db()
    assert admin.check_password("original")


def test_refuses_a_non_superadmin():
    _quarantine()
    User.objects.create_user(username="plain-user", password="original")
    with pytest.raises(CommandError, match="already be a superadmin"):
        call_command("recover_superadmin", "plain-user")


def test_establishes_the_durable_recovery_principal_under_quarantine(capsys):
    _quarantine()
    admin = User.objects.create_superuser(username="break-glass-2", password="original")

    call_command("recover_superadmin", "break-glass-2")

    state = DeploymentRecoveryState.objects.get(pk=1)
    assert state.recovery_principal_id == admin.pk
    admin.refresh_from_db()
    assert not admin.check_password("original")
    assert "One-time displayed password" in capsys.readouterr().out
    assert AuditLog.objects.filter(action="backup.recovery_superadmin_established").exists()


def test_unknown_username_cannot_create_a_recovery_account():
    _quarantine()
    with pytest.raises(CommandError, match="not found"):
        call_command("recover_superadmin", "missing-account", stdout=StringIO())
    assert not User.objects.exists()
    assert DeploymentRecoveryState.objects.get(pk=1).recovery_principal_id is None
    assert not AuditLog.objects.filter(action="backup.recovery_superadmin_established").exists()


def test_explicit_password_recovers_a_disabled_admin_without_acknowledging_quarantine():
    _quarantine()
    admin = User.objects.create_superuser(username="disabled-admin", password="original")
    User.objects.filter(pk=admin.pk).update(
        is_active=False, is_staff=False, access_status=User.AccessStatus.SUSPENDED,
        must_change_password=True,
    )
    output = StringIO()
    password = "explicit-break-glass-password"

    call_command("recover_superadmin", admin.username, password=password, stdout=output)

    admin.refresh_from_db()
    state = DeploymentRecoveryState.objects.get(pk=1)
    assert admin.check_password(password)
    assert admin.is_active and admin.is_staff and not admin.must_change_password
    assert admin.access_status == User.AccessStatus.ACTIVE
    assert state.mode == DeploymentRecoveryState.Mode.QUARANTINED
    assert state.recovery_principal_id == admin.pk
    entry = AuditLog.objects.get(action="backup.recovery_superadmin_established")
    assert entry.actor_id == admin.pk
    assert password not in str(entry.meta)
    assert f"One-time displayed password: {password}" in output.getvalue()


def test_generated_password_is_the_password_actually_installed(monkeypatch):
    _quarantine()
    admin = User.objects.create_superuser(username="generated-admin", password="original")
    monkeypatch.setattr(
        "apps.backup.management.commands.recover_superadmin.secrets.token_urlsafe",
        lambda size: "generated-one-time-password",
    )
    output = StringIO()
    call_command("recover_superadmin", admin.username, stdout=output)
    admin.refresh_from_db()
    assert admin.check_password("generated-one-time-password")
    assert "One-time displayed password: generated-one-time-password" in output.getvalue()
