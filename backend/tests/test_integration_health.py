import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.integrations import health as integration_health
from apps.integrations.models import EmailLog
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def health_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/integration-health"


@pytest.fixture(autouse=True)
def clear_worker_heartbeat():
    cache.delete(integration_health.WORKER_HEARTBEAT_CACHE_KEY)
    yield
    cache.delete(integration_health.WORKER_HEARTBEAT_CACHE_KEY)


def _email_log(makerspace, status, *, stream="hardware", subject="Notice", created_at=None, sent_at=None, error=""):
    log = EmailLog.objects.create(
        makerspace=makerspace,
        to_email="person@example.com",
        subject=subject,
        text_body="Body",
        stream=stream,
        status=status,
        error=error,
        sent_at=sent_at,
    )
    updates = {}
    if created_at is not None:
        updates["created_at"] = created_at
    if sent_at is not None:
        updates["sent_at"] = sent_at
    if updates:
        EmailLog.objects.filter(pk=log.pk).update(**updates)
        log.refresh_from_db()
    return log


def test_integration_health_requires_makerspace_manager_and_hides_other_archived_hidden():
    own_space = make_space("integration-health-own")
    other_space = make_space("integration-health-other")
    archived_space = make_space("integration-health-archived")
    archived_space.archived_at = timezone.now()
    archived_space.save(update_fields=["archived_at"])
    hidden_space = make_space("integration-health-hidden")
    hidden_space.superadmin_access_enabled = False
    hidden_space.save(update_fields=["superadmin_access_enabled"])
    manager = make_member("integration-health-manager", own_space)
    non_manager = make_member(
        "integration-health-non-manager",
        own_space,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    superadmin = make_user(
        "integration-health-superadmin",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )

    assert authenticated_client(non_manager).get(health_url(own_space)).status_code == 403
    manager_client = authenticated_client(manager)
    assert manager_client.get(health_url(other_space)).status_code == 404
    assert manager_client.get(health_url(archived_space)).status_code == 404
    assert authenticated_client(superadmin).get(health_url(hidden_space)).status_code == 404


def test_integration_health_counts_are_tenant_scoped_and_detect_stalled_and_last_failure():
    makerspace = make_space("integration-health-counts")
    other_space = make_space("integration-health-counts-other")
    manager = make_member("integration-health-counts-manager", makerspace)
    old_pending_at = timezone.now() - timezone.timedelta(
        minutes=integration_health.EMAIL_STALLED_MINUTES + 2
    )
    _email_log(makerspace, EmailLog.Status.PENDING, created_at=old_pending_at)
    _email_log(makerspace, EmailLog.Status.PENDING)
    _email_log(makerspace, EmailLog.Status.SENT, sent_at=timezone.now())
    _email_log(
        makerspace,
        EmailLog.Status.FAILED,
        subject="Latest failure",
        error="x" * 240,
        created_at=timezone.now() - timezone.timedelta(minutes=1),
    )
    _email_log(other_space, EmailLog.Status.FAILED)
    _email_log(other_space, EmailLog.Status.PENDING, created_at=old_pending_at)

    response = authenticated_client(manager).get(health_url(makerspace))

    assert response.status_code == 200
    email = response.data["email"]
    assert email["total"] == 4
    assert email["pending"] == 2
    assert email["sent"] == 1
    assert email["failed"] == 1
    assert email["stalled"] == 1
    assert email["status"] == "warn"
    assert response.data["status"] == "warn"
    assert email["last_failure"]["subject"] == "Latest failure"
    assert len(email["last_failure"]["error"]) == 200


def test_integration_health_deliveries_by_stream_returns_latest_sent_at():
    makerspace = make_space("integration-health-streams")
    manager = make_member("integration-health-streams-manager", makerspace)
    older = timezone.now() - timezone.timedelta(hours=2)
    latest_hardware = timezone.now() - timezone.timedelta(minutes=5)
    latest_printing = timezone.now() - timezone.timedelta(minutes=20)
    _email_log(makerspace, EmailLog.Status.SENT, stream="hardware", sent_at=older)
    _email_log(makerspace, EmailLog.Status.SENT, stream="hardware", sent_at=latest_hardware)
    _email_log(makerspace, EmailLog.Status.SENT, stream="printing", sent_at=latest_printing)

    response = authenticated_client(manager).get(health_url(makerspace))

    assert response.status_code == 200
    deliveries = response.data["deliveries_by_stream"]
    assert parse_datetime(deliveries["hardware"]) == latest_hardware
    assert parse_datetime(deliveries["printing"]) == latest_printing


@override_settings(CELERY_TASK_ALWAYS_EAGER=False, CELERY_BROKER_URL="redis://localhost:6379/0")
def test_integration_health_worker_last_seen_and_stale_from_cache():
    makerspace = make_space("integration-health-worker")
    manager = make_member("integration-health-worker-manager", makerspace)
    last_seen = timezone.now().replace(microsecond=0)
    cache.set(integration_health.WORKER_HEARTBEAT_CACHE_KEY, last_seen.isoformat(), timeout=None)

    response = authenticated_client(manager).get(health_url(makerspace))

    assert response.status_code == 200
    assert response.data["worker"]["broker_configured"] is True
    assert response.data["worker"]["eager"] is False
    assert parse_datetime(response.data["worker"]["last_seen"]) == last_seen
    assert response.data["worker"]["stale"] is False

    old_seen = timezone.now() - timezone.timedelta(
        minutes=integration_health.WORKER_STALE_MINUTES + 1
    )
    cache.set(integration_health.WORKER_HEARTBEAT_CACHE_KEY, old_seen.isoformat(), timeout=None)
    stale = authenticated_client(manager).get(health_url(makerspace))

    assert stale.status_code == 200
    assert stale.data["worker"]["stale"] is True
    assert stale.data["worker"]["status"] == "warn"
    assert stale.data["status"] == "warn"


def test_integration_health_subsection_failure_is_fail_safe(monkeypatch):
    makerspace = make_space("integration-health-failsafe")
    manager = make_member("integration-health-failsafe-manager", makerspace)

    def raise_smtp(_makerspace):
        raise RuntimeError("smtp health exploded")

    monkeypatch.setattr("apps.integrations.health_status._smtp_section", raise_smtp)

    response = authenticated_client(manager).get(health_url(makerspace))

    assert response.status_code == 200
    assert response.data["smtp"] == {"status": "unknown", "detail": "RuntimeError"}
    assert response.data["status"] == "warn"


def test_integration_health_unauthenticated_is_rejected():
    makerspace = make_space("integration-health-anonymous")

    response = APIClient().get(health_url(makerspace))

    assert response.status_code in {401, 403}
