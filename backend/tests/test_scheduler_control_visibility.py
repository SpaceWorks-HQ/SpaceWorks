"""The beat-less scheduler's failures are visible in `/control/` (cloud lane).

The cron drivers swallow `run_scheduled_tasks`' exit status so one failing task cannot
stop the loop, which made `PeriodicTaskRun.last_error` the only record of a failure -- and
no console showed it. The page is superadmin-only and read-only.
"""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.operations.models import PeriodicTaskRun
from tests.return_helpers import make_member, make_space, make_user
from tests.accounts.mfa_helpers import force_mfa_login

pytestmark = pytest.mark.django_db

URL = "admin:operations_periodictaskrun_changelist"


def _client(user):
    client = Client()
    force_mfa_login(client, user)
    return client


def test_a_superadmin_sees_each_task_and_its_last_failure():
    PeriodicTaskRun.objects.create(name="return-reminders", last_error="SMTPServerDisconnected")
    PeriodicTaskRun.objects.create(name="purge-auth-challenges")
    root = make_user(
        "scheduler-root", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
        is_staff=True, is_superuser=True,
    )

    response = _client(root).get(reverse(URL))

    body = response.content.decode()
    assert response.status_code == 200
    assert "return-reminders" in body and "purge-auth-challenges" in body
    assert "SMTPServerDisconnected" in body
    assert "Failed" in body


def test_the_page_is_read_only():
    from django.contrib import admin

    model_admin = admin.site._registry[PeriodicTaskRun]
    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_delete_permission(None) is False


def test_a_space_manager_cannot_open_it():
    space = make_space("scheduler-sm")
    manager = make_member("scheduler-sm-manager", space)
    manager.is_staff = True
    manager.save(update_fields=["is_staff"])

    response = _client(manager).get(reverse(URL))

    assert response.status_code in {302, 403, 404}


def test_sidebar_has_every_platform_integration_and_the_scheduler():
    from config.unfold import UNFOLD

    labels = {
        str(item["title"])
        for group in UNFOLD["SIDEBAR"]["navigation"]
        for item in group["items"]
    }
    assert {
        "Platform SMS", "Platform push", "Login methods", "Social sign-in",
        "OIDC providers", "Scheduled task runs",
    } <= labels
