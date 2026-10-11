"""Monitoring reads preserve state and report real offsite/channel failures."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup.models import BackupDestination, BackupDestinationUpload
from apps.integrations.models import PlatformEmailSettings, PlatformPushSettings, PlatformSmsSettings
from apps.operations.platform_signals import offsite_snapshot
from tests.return_helpers import authenticated_client, make_member, make_space
from tests.test_platform_monitoring_api import DASHBOARD, PROBLEMS, operator, usage_url

pytestmark = pytest.mark.django_db


def verified_copy(destination, space, **overrides):
    now = timezone.now()
    values = dict(
        destination=destination, scope_snapshot="makerspace", makerspace_id_snapshot=space.pk,
        archive_id_snapshot=uuid.uuid4(), archive_completed_at_snapshot=now,
        expected_size_bytes=1, expected_sha256="c" * 64, integrity_source="archive_row",
        remote_locator="safe", next_attempt_at=now, expires_at=now + timedelta(days=7),
        state="bytes_verified", verified_at=now, verified_size_bytes=1,
    )
    values.update(overrides)
    return BackupDestinationUpload.objects.create(**values)


def test_monitoring_gets_and_scheduled_checks_never_create_integration_settings():
    from apps.operations.tasks_platform import PROBLEM_RUN_CACHE_KEY, run_platform_problem_checks_task
    from django.core.cache import cache

    space = make_space("read-only-health")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"email", "telegram"})
    space.save(update_fields=["enabled_modules"])
    models = (PlatformEmailSettings, PlatformPushSettings, PlatformSmsSettings)
    for model in models:
        model.objects.all().delete()
    client = authenticated_client(operator())
    before = AuditLog.objects.count()
    try:
        assert client.get(DASHBOARD).status_code == 200
        assert client.get(PROBLEMS).status_code == 200
        run_platform_problem_checks_task()
        assert all(not model.objects.exists() for model in models)
        assert AuditLog.objects.count() == before
    finally:
        cache.delete(PROBLEM_RUN_CACHE_KEY)


@pytest.mark.parametrize("source", ["tenant", "platform"])
def test_problem_email_snapshot_checks_credentials_without_writing(source, monkeypatch):
    from apps.makerspaces.models import Makerspace
    from apps.operations.platform_integration_health import integration_snapshot
    from apps.operations.platform_checks import email_check

    space = make_space("read-only-smtp")
    space.enabled_modules = ["email"]
    if source == "tenant":
        space.smtp_host = "smtp.example.com"
        password_owner = Makerspace
    else:
        PlatformEmailSettings.objects.create(pk=1, smtp_host="smtp.example.com")
        password_owner = PlatformEmailSettings
    assert email_check({"space": space, "health": integration_snapshot(space)}, timezone.now())[0]["status"] == "ok"

    def fail(*args):
        raise ValueError("smtp-password-secret")
    monkeypatch.setattr(password_owner, "get_smtp_password", fail)
    rows = email_check({"space": space, "health": integration_snapshot(space)}, timezone.now())
    assert rows[0]["status"] == "warn"
    assert "smtp-password-secret" not in str(rows)


@pytest.mark.parametrize("code", ["read_back_failed", "delete_failed"])
def test_verified_copy_transport_or_retention_failure_is_not_healthy(code):
    space = make_space("offsite-reverify")
    destination = BackupDestination.objects.create(name="reverify", bucket="archives")
    verified_copy(destination, space, last_error_code=code)
    assert offsite_snapshot([space.pk])[0]["has_error"] is True


def test_latest_probe_failure_and_recovery_are_reported_without_provider_details():
    from apps.backup import offsite_client
    from apps.backup.services_offsite import probe_destination
    from unittest.mock import patch

    space = make_space("offsite-probe")
    destination = BackupDestination.objects.create(name="probe", bucket="archives")
    verified_copy(destination, space)
    with patch("apps.backup.services_offsite.offsite_client.probe",
               side_effect=offsite_client.OffsiteDestinationError("probe_write_failed")):
        probe_destination(destination, operator())
    rows = offsite_snapshot([space.pk])
    assert rows[0]["has_error"] is True
    assert "probe_write_failed" not in str(rows)
    with patch("apps.backup.services_offsite.offsite_client.probe"):
        probe_destination(destination, None)
    assert offsite_snapshot([space.pk])[0]["has_error"] is False


def test_hidden_copy_error_and_destination_rollup_do_not_leak():
    visible, hidden = make_space("visible-copy"), make_space("hidden-copy")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    destination = BackupDestination.objects.create(name="private-error", bucket="archives",
                                                 last_error_code="hidden-error")
    verified_copy(destination, visible)
    verified_copy(destination, hidden, last_error_code="hidden-error")
    response = authenticated_client(operator()).get(DASHBOARD)
    assert response.status_code == 200
    assert response.data["offsite"][0]["has_error"] is False
    assert "hidden-error" not in str(response.data)


def test_usage_custom_origin_accepts_only_own_manager_and_space(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space.example"
    settings.INFRA_HOSTS = [*settings.INFRA_HOSTS, "testserver"]
    space = make_space("scoped-usage")
    space.frontend_domain = "scoped.example.com"
    space.frontend_domain_status = "verified"
    space.save(update_fields=["frontend_domain", "frontend_domain_status"])
    other = make_space("unrelated-usage")
    client = authenticated_client(make_member("scoped-manager", space))
    assert client.get(usage_url(space), HTTP_HOST="testserver", HTTP_ORIGIN="https://scoped.example.com").status_code == 200
    assert client.get(usage_url(other), HTTP_HOST="testserver", HTTP_ORIGIN="https://scoped.example.com").status_code == 403


def test_monitoring_still_works_when_updater_is_disabled():
    space = make_space("no-updater")
    space.enabled_modules = [key for key in space.enabled_modules if key != "updates"]
    space.save(update_fields=["enabled_modules"])
    client = authenticated_client(operator())
    assert client.get(DASHBOARD).data["updates"] is None
    response = client.get(PROBLEMS)
    assert response.status_code == 200
    assert next(row for row in response.data["results"] if row["key"] == "updates")["status"] == "ok"


@pytest.mark.parametrize("url", [DASHBOARD, PROBLEMS])
@pytest.mark.parametrize("field,value", [
    ("must_change_password", True), ("is_active", False), ("access_status", "restricted"),
])
def test_platform_endpoints_refuse_ineligible_superadmin(url, field, value):
    user = operator()
    client = authenticated_client(user)
    assert client.get(url).status_code == 200
    setattr(user, field, value)
    user.save(update_fields=[field])
    assert authenticated_client(user).get(url).status_code == 403
