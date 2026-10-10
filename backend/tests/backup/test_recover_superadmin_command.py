"""`recover_superadmin` (audit gap 10): the privileged host's quarantine break glass."""

import pytest
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
