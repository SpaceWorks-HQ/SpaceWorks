"""The in-app updater after a crash, and for every actor (cloud lane).

A host killed mid-update (reboot, OOM, power) never runs `update.sh`'s cleanup trap, so the
singleton stayed RUNNING forever: the next claim kept it, `queue_update` refuses to queue
over it, and the console disables both controls while it is RUNNING. Claim only ever runs
under the host update lock, so a RUNNING row it observes is stale by construction.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.updates import services
from apps.updates.models import PlatformUpdateSettings
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db

OLD = "0.5.0-main.1.aaaaaaaaaaaa"
NEW = "0.5.0-main.2.bbbbbbbbbbbb"


def _stuck_running():
    settings = PlatformUpdateSettings.load()
    settings.status = PlatformUpdateSettings.Status.RUNNING
    settings.target_version = NEW
    settings.save()
    return settings


def _superadmin(name):
    return make_user(name, role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)


def test_a_claim_over_a_dead_run_records_the_interruption():
    _stuck_running()

    assert services.claim_update(current_version=OLD, available_version=NEW) is False

    settings = PlatformUpdateSettings.load()
    assert settings.status == PlatformUpdateSettings.Status.FAILED
    assert settings.last_error == services.INTERRUPTED_MESSAGE
    assert settings.target_version == ""


def test_after_the_interruption_the_operator_can_queue_again():
    _stuck_running()
    services.claim_update(current_version=OLD, available_version=NEW)

    services.queue_update()

    assert PlatformUpdateSettings.load().status == PlatformUpdateSettings.Status.QUEUED
    assert services.claim_update(current_version=OLD, available_version=NEW) is True


def test_a_dead_run_with_automatic_updates_on_is_retried_by_the_same_claim():
    settings = _stuck_running()
    settings.automatic_updates_enabled = True
    settings.save(update_fields=("automatic_updates_enabled", "updated_at"))

    assert services.claim_update(current_version=OLD, available_version=NEW) is True
    settings.refresh_from_db()
    assert settings.status == PlatformUpdateSettings.Status.RUNNING
    assert settings.last_error == ""


def test_a_dead_run_that_had_already_installed_the_release_settles_idle():
    _stuck_running()

    assert services.claim_update(current_version=NEW, available_version=NEW) is False

    settings = PlatformUpdateSettings.load()
    assert settings.status == PlatformUpdateSettings.Status.IDLE
    assert settings.last_error == ""


def test_update_now_during_a_running_update_is_audited_as_a_no_op():
    _stuck_running()
    root = _superadmin("updates-noop-root")

    response = authenticated_client(root).post(reverse("admin-platform-update-now"), format="json")

    assert response.status_code == 202
    assert response.data["status"] == PlatformUpdateSettings.Status.RUNNING
    assert AuditLog.objects.get(action="platform.update_requested").meta == {"noop": True}


def test_a_real_queue_is_audited_as_a_change():
    root = _superadmin("updates-queue-root")

    authenticated_client(root).post(reverse("admin-platform-update-now"), format="json")

    assert AuditLog.objects.get(action="platform.update_requested").meta == {"noop": False}


@pytest.mark.parametrize("method", ["get", "patch", "post"])
def test_a_space_manager_cannot_touch_the_updater(method):
    space = make_space("updates-sm-space")
    manager = authenticated_client(make_member("updates-sm", space))
    url = reverse("admin-platform-update-now" if method == "post" else "admin-platform-update-settings")

    response = getattr(manager, method)(url, {"automatic_updates_enabled": True}, format="json")

    assert response.status_code == 403
    assert not AuditLog.objects.filter(action__startswith="platform.update").exists()


@pytest.mark.parametrize("method", ["get", "patch", "post"])
def test_anonymous_callers_are_refused(method):
    url = reverse("admin-platform-update-now" if method == "post" else "admin-platform-update-settings")

    response = getattr(APIClient(), method)(url, {}, format="json")

    assert response.status_code == 401
