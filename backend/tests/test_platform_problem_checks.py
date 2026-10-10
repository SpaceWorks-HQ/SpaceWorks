"""All registered checks have explicit normal, warning and failure behavior."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.operations import platform_checks as checks


def status(rows):
    assert all(row["message"] and row["fix_url"].startswith("/") for row in rows)
    return rows[0]["status"]


@pytest.mark.parametrize("hours,expected", [(1, "ok"), (37, "warn"), (73, "error")])
def test_backup_age_is_relative_to_schedule(hours, expected):
    now = timezone.now()
    data = {"automatic_enabled": True, "has_error": False, "status": "complete",
            "last_success_at": now - timedelta(hours=hours), "cadence_minutes": 1440}
    assert status(checks.backup_check(data, now)) == expected


def test_backup_disabled_missing_and_failed():
    data = {"automatic_enabled": False, "has_error": False, "status": "never",
            "last_success_at": None, "cadence_minutes": 1440}
    assert status(checks.backup_check(data, timezone.now())) == "ok"
    data["automatic_enabled"] = True
    assert status(checks.backup_check(data, timezone.now())) == "warn"
    data["has_error"] = True
    assert status(checks.backup_check(data, timezone.now())) == "error"


@pytest.mark.parametrize("state,error,expected", [
    ("bytes_verified", False, "ok"), ("pending", False, "warn"),
    ("pending", True, "error"), ("abandoned", False, "error"),
])
def test_offsite_states(state, error, expected):
    assert status(checks.offsite_check([{"name": "remote", "state": state, "has_error": error}],
                                     timezone.now())) == expected


def test_offsite_not_configured_is_warning():
    assert status(checks.offsite_check([], timezone.now())) == "warn"


@pytest.mark.parametrize("expected", ["ok", "warn", "error"])
def test_scheduler_reports_freshness(expected):
    assert status(checks.scheduler_check([{"name": "job", "status": expected}], timezone.now())) == expected


@pytest.mark.parametrize("update_state,pending,expected", [
    ("idle", False, "ok"), ("queued", True, "warn"), ("failed", False, "error"),
])
def test_updates_states(update_state, pending, expected):
    assert status(checks.updates_check({"status": update_state, "pending": pending}, timezone.now())) == expected


def test_updates_disabled_is_ok():
    assert status(checks.updates_check(None, timezone.now())) == "ok"


def tenant_data():
    return {
        "space": SimpleNamespace(pk=7, name="Lab", slug="lab", enabled_modules=["email", "telegram"],
                                 frontend_domain="lab.example.com", frontend_domain_status="verified"),
        "usage": {"resources": [{"key": "storage", "used": 10, "limit": 100}]},
        "health": {
            "email": {"status": "ok", "failed": 0}, "smtp": {"status": "ok", "configured": True},
            "telegram": {"status": "ok", "configured": True},
            "chat_destinations": {"status": "ok", "destinations": [], "legacy_deliveries": {}},
        },
    }


@pytest.mark.parametrize("configured,failed,expected", [(True, 0, "ok"), (False, 0, "warn"), (True, 1, "error")])
def test_email_health(configured, failed, expected):
    data = tenant_data()
    data["health"]["smtp"]["configured"] = configured
    data["health"]["email"]["failed"] = failed
    assert status(checks.email_check(data, timezone.now())) == expected


@pytest.mark.parametrize("configured,failed,expected", [(True, 0, "ok"), (False, 0, "warn"), (True, 1, "error")])
def test_telegram_health_including_destinations(configured, failed, expected):
    data = tenant_data()
    data["health"]["chat_destinations"]["destinations"] = [
        {"channel": "telegram", "is_active": True, "configured": configured, "failed": failed},
    ]
    assert status(checks.telegram_check(data, timezone.now())) == expected


@pytest.mark.parametrize("function", [checks.email_check, checks.telegram_check])
def test_channel_off_does_not_raise_false_alarm(function):
    data = tenant_data()
    data["space"].enabled_modules = []
    assert status(function(data, timezone.now())) == "ok"


@pytest.mark.parametrize("section", ["smtp", "email"])
def test_unknown_email_health_is_warning(section):
    data = tenant_data()
    data["health"][section] = {"status": "unknown", "detail": "secret"}
    rows = checks.email_check(data, timezone.now())
    assert status(rows) == "warn"
    assert "secret" not in str(rows)


@pytest.mark.parametrize("used,limit,expected", [(10, 100, "ok"), (90, 100, "warn"),
    (101, 100, "error"), (1000, None, "ok"), (0, 0, "ok"), (1, 0, "error")])
def test_storage_boundaries(used, limit, expected):
    data = tenant_data()
    data["usage"]["resources"][0].update(used=used, limit=limit)
    assert status(checks.storage_check(data, timezone.now())) == expected


@pytest.mark.parametrize("domain_state,expected", [("verified", "ok"), ("pending", "warn"), ("failed", "error")])
def test_domain_verification(domain_state, expected):
    data = tenant_data()
    data["space"].frontend_domain_status = domain_state
    rows = checks.domain_check(data, timezone.now())
    assert status(rows) == expected
    assert rows[0]["makerspace_id"] == 7


def test_registry_is_explicit_and_unique():
    assert {check.key for check in checks.PROBLEM_CHECKS} == {
        "backup", "offsite", "scheduler", "updates", "email", "telegram", "storage", "domain",
    }
    assert len(checks.PROBLEM_CHECKS) == 8


def test_inactive_telegram_destinations_suppress_legacy_configuration():
    data = tenant_data()
    data["health"]["chat_destinations"]["destinations"] = [
        {"channel": "telegram", "is_active": False, "configured": True, "failed": 0},
    ]
    assert status(checks.telegram_check(data, timezone.now())) == "warn"
