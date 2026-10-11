from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.integrations.models import DailyNotificationCounter, EmailLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.operations.models_scheduling import PeriodicTaskRun
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db
DASHBOARD = "/api/v1/admin/platform/dashboard"
PROBLEMS = "/api/v1/admin/platform/problems"


def operator():
    return make_user("platform-operator", role=User.Role.SUPERADMIN, is_superuser=True, is_staff=True)


def usage_url(space):
    return f"/api/v1/admin/makerspace/{space.pk}/usage"


@pytest.mark.parametrize("url", [DASHBOARD, PROBLEMS])
def test_platform_endpoints_require_active_superadmin(url):
    space = make_space("permissions")
    manager = make_member("manager", space)
    assert APIClient().get(url).status_code == 401
    assert authenticated_client(manager).get(url).status_code == 403
    user = operator()
    user.access_status = User.AccessStatus.SUSPENDED
    user.save(update_fields=["access_status"])
    assert authenticated_client(user).get(url).status_code == 403


def test_dashboard_excludes_hidden_and_counts_lifecycle_without_tenant_details():
    visible = make_space("visible")
    hidden = make_space("hidden")
    hidden.superadmin_access_enabled = False
    hidden.storage_bytes_used = 999999
    hidden.save(update_fields=["superadmin_access_enabled", "storage_bytes_used"])
    importing = make_space("importing")
    Makerspace.objects.filter(pk=importing.pk).update(lifecycle_state="importing")
    archived = make_space("archived")
    Makerspace.objects.filter(pk=archived.pk).update(archived_at=timezone.now())
    EmailLog.objects.create(makerspace=hidden, to_email="secret@example.com", subject="secret",
                            text_body="secret", status="failed")
    response = authenticated_client(operator()).get(DASHBOARD)
    assert response.status_code == 200
    assert response.data["tenants_by_state"] == {"active": 1, "importing": 1, "aborted": 0, "archived": 1}
    assert [row["id"] for row in response.data["tenants"]] == [visible.pk]
    assert response.data["usage_totals"]["storage"] == 0
    assert response.data["failed_deliveries"]["email"] == 0
    assert "secret" not in str(response.data)


def test_problems_exclude_hidden_even_when_superadmin_is_a_manager_there():
    hidden = make_space("sovereign")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    user = operator()
    MakerspaceMembership.objects.create(user=user, makerspace=hidden, role="space_manager")
    client = authenticated_client(user)
    assert client.get(usage_url(hidden)).status_code == 200
    response = client.get(PROBLEMS)
    assert response.status_code == 200
    assert all(row["makerspace_id"] is None for row in response.data["results"])
    assert not client.get(DASHBOARD).data["tenants"]


def test_usage_is_scoped_and_honors_managed_overrides(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space.example"
    settings.INFRA_HOSTS = [*settings.INFRA_HOSTS, "testserver"]
    space, other = make_space("own"), make_space("other")
    space.resource_limit_overrides = {"products": 50, "storage": 1024, "email": None}
    space.storage_bytes_used = 512
    space.save(update_fields=["resource_limit_overrides", "storage_bytes_used"])
    DailyNotificationCounter.objects.create(makerspace=space, day=timezone.now().date(), channel="telegram", count=3)
    DailyNotificationCounter.objects.create(makerspace=other, day=timezone.now().date(), channel="telegram", count=20)
    client = authenticated_client(make_member("usage-manager", space))
    response = client.get(usage_url(space), HTTP_HOST="testserver")
    assert response.status_code == 200
    assert response.data["managed"] is True
    resources = {row["key"]: row for row in response.data["resources"]}
    assert resources["storage"]["used"] == 512
    assert resources["storage"]["limit"] == 1024
    assert resources["products"]["limit"] == 50
    assert resources["email"]["limit"] is None
    assert resources["telegram"]["used"] == 3
    assert client.get(usage_url(other), HTTP_HOST="testserver").status_code == 404
    reader = make_member("usage-inventory", space, MakerspaceMembership.Role.INVENTORY_MANAGER)
    assert authenticated_client(reader).get(usage_url(space), HTTP_HOST="testserver").status_code == 403


def test_usage_rejects_archived_hidden_and_foreign_origin(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space.example"
    settings.INFRA_HOSTS = [*settings.INFRA_HOSTS, "testserver"]
    space = make_space("origin-own")
    other = make_space("origin-other")
    other.frontend_domain = "other.example.com"
    other.frontend_domain_status = "verified"
    other.save(update_fields=["frontend_domain", "frontend_domain_status"])
    user = operator()
    client = authenticated_client(user)
    assert client.get(usage_url(space), HTTP_HOST="testserver", HTTP_ORIGIN="https://other.example.com").status_code == 403
    assert client.get(DASHBOARD, HTTP_HOST="testserver", HTTP_ORIGIN="https://other.example.com").status_code == 403
    assert client.get(PROBLEMS, HTTP_HOST="testserver", HTTP_ORIGIN="https://other.example.com").status_code == 403
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled"])
    assert client.get(usage_url(space), HTTP_HOST="testserver").status_code == 404
    manager = make_member("own-manager", space)
    assert authenticated_client(manager).get(usage_url(space), HTTP_HOST="testserver").status_code == 200
    space.archived_at = timezone.now()
    space.save(update_fields=["archived_at"])
    assert authenticated_client(manager).get(usage_url(space), HTTP_HOST="testserver").status_code == 404


def test_self_host_usage_has_no_limits(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    space = make_space("unlimited")
    response = authenticated_client(make_member("self-manager", space)).get(usage_url(space))
    assert response.status_code == 200
    assert response.data["managed"] is False
    assert all(row["limit"] is None for row in response.data["resources"])


def test_each_check_failure_is_isolated_and_provider_strings_are_not_returned(monkeypatch):
    from apps.operations import platform_problems

    def fail():
        raise RuntimeError("credential=top-secret")
    monkeypatch.setattr(platform_problems, "backup_snapshot", fail)
    response = authenticated_client(operator()).get(PROBLEMS)
    assert response.status_code == 200
    results = response.data["results"]
    assert next(row for row in results if row["key"] == "backup")["status"] == "warn"
    assert any(row["key"] == "scheduler" for row in results)
    assert "top-secret" not in str(response.data)


@pytest.mark.parametrize("minutes,error,expected", [(1, "", "ok"), (181, "", "warn"), (1, "Secret", "error")])
def test_scheduler_freshness_uses_three_cadences(minutes, error, expected):
    from apps.operations.platform_signals import scheduler_snapshot

    now = timezone.now()
    PeriodicTaskRun.objects.create(name="return-reminders", last_run_at=now - timedelta(minutes=minutes), last_error=error)
    row = next(row for row in scheduler_snapshot(now) if row["name"] == "return-reminders")
    assert row["status"] == expected
    assert "Secret" not in str(row)


def test_scheduler_missing_execution_is_warn():
    from apps.operations.platform_signals import scheduler_snapshot
    assert all(row["status"] == "warn" for row in scheduler_snapshot())


def test_usage_requires_authentication_and_refuses_initial_password():
    space = make_space("initial-password")
    assert APIClient().get(usage_url(space)).status_code == 401
    user = make_member("initial-manager", space)
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])
    client = authenticated_client(user)
    assert client.get(usage_url(space)).status_code == 403
    assert client.get(DASHBOARD).status_code == 403


def test_offsite_tenant_uploads_exclude_hidden_snapshots():
    import uuid
    from apps.backup.models_offsite import BackupDestination, BackupDestinationUpload
    from apps.operations.platform_signals import offsite_snapshot

    visible, hidden = make_space("offsite-visible"), make_space("offsite-hidden")
    destination = BackupDestination.objects.create(name="remote", bucket="archives")
    now = timezone.now()
    common = dict(destination=destination, scope_snapshot="makerspace", format_snapshot="sealed",
                  archive_completed_at_snapshot=now, expected_size_bytes=1,
                  expected_sha256="a" * 64, integrity_source="archive_row", remote_locator="safe",
                  next_attempt_at=now, expires_at=now + timedelta(days=7))
    BackupDestinationUpload.objects.create(**common, archive_id_snapshot=uuid.uuid4(),
        makerspace_id_snapshot=visible.pk, state="bytes_verified", verified_at=now,
        verified_size_bytes=1)
    BackupDestinationUpload.objects.create(**common, archive_id_snapshot=uuid.uuid4(),
        makerspace_id_snapshot=hidden.pk, last_error_code="hidden-failure")
    rows = offsite_snapshot([visible.pk])
    assert rows[0]["state"] == "bytes_verified"
    assert rows[0]["has_error"] is False
    assert "hidden-failure" not in str(rows)


def test_dashboard_reads_do_not_create_singleton_settings():
    from apps.backup.models import PlatformBackupSettings
    from apps.updates.models import PlatformUpdateSettings
    PlatformBackupSettings.objects.all().delete()
    PlatformUpdateSettings.objects.all().delete()
    client = authenticated_client(operator())
    assert client.get(DASHBOARD).status_code == 200
    assert client.get(PROBLEMS).status_code == 200
    assert not PlatformBackupSettings.objects.exists()
    assert not PlatformUpdateSettings.objects.exists()


def test_usage_tombstoned_counters_are_unavailable(settings):
    settings.TOMBSTONED_APPS = {"events", "bookings", "updates"}
    space = make_space("tombstoned-usage")
    client = authenticated_client(make_member("tombstone-manager", space))
    response = client.get(usage_url(space))
    assert response.status_code == 200
    resources = {r["key"]: r for r in response.data["resources"]}
    assert resources["events"]["used"] is None
    assert resources["bookings"]["used"] is None


def test_offsite_older_visible_failure_is_not_masked_by_a_newer_success():
    import uuid
    from apps.backup.models_offsite import BackupDestination, BackupDestinationUpload
    from apps.operations.platform_signals import offsite_snapshot
    space = make_space("offsite-outstanding")
    destination = BackupDestination.objects.create(name="outstanding", bucket="archives")
    now = timezone.now()
    common = dict(destination=destination, scope_snapshot="makerspace", makerspace_id_snapshot=space.pk,
                  archive_completed_at_snapshot=now, expected_size_bytes=1, expected_sha256="b" * 64,
                  integrity_source="archive_row", remote_locator="safe", next_attempt_at=now,
                  expires_at=now + timedelta(days=7))
    BackupDestinationUpload.objects.create(**common, archive_id_snapshot=uuid.uuid4(), last_error_code="upload_failed")
    BackupDestinationUpload.objects.create(**common, archive_id_snapshot=uuid.uuid4(), state="bytes_verified",
                                          verified_at=now, verified_size_bytes=1)
    assert offsite_snapshot([space.pk])[0]["has_error"] is True
