from contextlib import contextmanager, nullcontext
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.operation_lock import OperationLockUnavailable
from apps.updates import services
from apps.updates.models import PlatformUpdateSettings
from apps.updates.recovery import is_stuck, TIMEOUT_MESSAGE
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db
NEW = "0.5.0-main.2.bbbbbbbbbbbb"
RECOVER = "admin-platform-update-recover"
ROLLBACK = "admin-platform-update-rollback"


def stuck_row(*, seconds=7201):
    row = PlatformUpdateSettings.load()
    row.status = "running"
    row.running_since = timezone.now() - timedelta(seconds=seconds)
    row.target_version = NEW
    row.save()
    return row


def root_client(**changes):
    return authenticated_client(make_user("timeout-root", role=User.Role.SUPERADMIN, access_status="active", **changes))


@pytest.mark.parametrize("seconds,expected", [(7199, False), (7200, False), (7201, True)])
def test_stuck_detection_uses_the_started_time_and_strict_timeout(seconds, expected):
    row = stuck_row(seconds=seconds)
    assert is_stuck(row, now=row.running_since + timedelta(seconds=seconds)) is expected


def test_unrelated_settings_write_does_not_restart_the_update_timeout():
    row = stuck_row()
    row.automatic_updates_enabled = True
    row.save()
    assert is_stuck(row)


def test_configured_timeout_and_nonrunning_states(settings):
    settings.UPDATE_RUNNING_TIMEOUT_SECONDS = 60
    row = stuck_row(seconds=61)
    assert is_stuck(row)
    row.status = "failed"
    assert not is_stuck(row)


def test_get_reports_stuck_without_mutation_or_releasing_any_lock():
    stuck_row()
    response = root_client().get(reverse("admin-platform-update-settings"))
    assert response.status_code == 200 and response.data["is_stuck"] is True
    assert PlatformUpdateSettings.load().status == "running"
    assert not AuditLog.objects.filter(action="platform.update_recovered").exists()


def test_timed_recovery_is_idempotent_audited_and_releases_the_logical_lock():
    stuck_row()
    client = root_client()
    with patch("apps.backup.operation_lock.deployment_operation_lock", return_value=nullcontext()) as lock:
        response = client.post(reverse(RECOVER))
        repeated = client.post(reverse(RECOVER))
    assert response.status_code == repeated.status_code == 200
    assert response.data["status"] == "failed"
    assert response.data["target_version"] == "" and response.data["running_since"] is None
    assert response.data["last_error"] == TIMEOUT_MESSAGE
    lock.assert_called_once()
    event = AuditLog.objects.get(action="platform.update_recovered")
    assert event.actor.username == "timeout-root" and event.meta["target_version"] == NEW
    assert services.queue_update().status == "queued"


def test_recent_running_update_cannot_be_recovered_and_never_touches_the_host_lock():
    stuck_row(seconds=60)
    with patch("apps.backup.operation_lock.deployment_operation_lock") as lock:
        response = root_client().post(reverse(RECOVER))
    assert response.status_code == 400 and response.data["reason"] == "update_not_stuck"
    lock.assert_not_called()
    assert PlatformUpdateSettings.load().status == "running"


def test_a_live_or_inaccessible_host_lock_refuses_timed_recovery():
    stuck_row()
    with patch("apps.backup.operation_lock.deployment_operation_lock", side_effect=OperationLockUnavailable("busy")):
        response = root_client().post(reverse(RECOVER))
    assert response.status_code == 400 and response.data["reason"] == "host_operation_active"
    assert PlatformUpdateSettings.load().status == "running"
    assert not AuditLog.objects.filter(action="platform.update_recovered").exists()


def test_recovery_rechecks_state_after_acquiring_the_host_lock():
    stuck_row()

    @contextmanager
    def completed_before_lock():
        services.complete_update(NEW)
        yield

    with patch("apps.backup.operation_lock.deployment_operation_lock", completed_before_lock):
        response = root_client().post(reverse(RECOVER))
    assert response.status_code == 200 and response.data["status"] == "idle"
    assert not AuditLog.objects.filter(action="platform.update_recovered").exists()


def test_host_claim_recovery_is_also_audited_with_a_system_actor():
    stuck_row(seconds=30)
    services.claim_update(current_version="0.5.0-main.1.aaaaaaaaaaaa", available_version=NEW)
    assert AuditLog.objects.get(action="platform.update_recovered").actor is None


@pytest.mark.parametrize("route", [RECOVER, ROLLBACK])
def test_new_update_actions_refuse_managers_and_anonymous_callers(route):
    space = make_space("timeout-permissions")
    manager = make_member("timeout-manager", space)
    assert authenticated_client(manager).post(reverse(route), {}, format="json").status_code == 403
    assert APIClient().post(reverse(route), {}, format="json").status_code == 401
    assert not AuditLog.objects.filter(action__startswith="platform.update").exists()


@pytest.mark.parametrize("route", [RECOVER, ROLLBACK])
@pytest.mark.parametrize("changes", [{"is_active": False}, {"access_status": "restricted"}, {"must_change_password": True}])
def test_new_update_actions_require_an_active_unrestricted_rotated_superadmin(route, changes):
    values = {"role": User.Role.SUPERADMIN, "access_status": "active", **changes}
    actor = make_user("timeout-inactive-root", **values)
    assert authenticated_client(actor).post(reverse(route), {}, format="json").status_code == 403


@pytest.mark.parametrize("route", [RECOVER, ROLLBACK])
def test_module_off_actions_return_typed_400(route):
    with patch("apps.admin_api.views_platform_updates.updates_module_enabled", return_value=False):
        response = root_client().post(reverse(route), {}, format="json")
    assert response.status_code == 400 and response.data["reason"] == "module_disabled"
