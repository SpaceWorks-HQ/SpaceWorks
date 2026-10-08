"""Staff API for audit verification runs: always async, scoped, bounded, deduplicated."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.accounts import rbac
from apps.audit import services as audit
from apps.audit import verification_runs as runs
from apps.audit.models import AuditLog, AuditVerificationRun, AuditVerificationRunEvent
from apps.makerspaces.models import MakerspaceMembership
from tests.audit_explorer_helpers import (
    client_for,
    custom_role_member,
    member_with,
    org_auditor,
    space,
    superadmin,
)

pytestmark = pytest.mark.django_db
State = AuditVerificationRunEvent.State


@pytest.fixture(autouse=True)
def _no_task(monkeypatch):
    queued = []
    monkeypatch.setattr(runs, "_enqueue", lambda run_id, countdown=0: queued.append(run_id))
    cache.clear()
    return queued


def _url(makerspace, run_id=None):
    if run_id is None:
        return reverse("admin-audit-verifications", args=[makerspace.pk])
    return reverse("admin-audit-verification-detail", args=[makerspace.pk, run_id])


def _post(client, makerspace, body=None):
    return client.post(_url(makerspace), body or {}, format="json")


def test_post_is_202_with_status_url_and_records_an_audit_row(
    django_capture_on_commit_callbacks, _no_task
):
    makerspace = space("vapi-basic")
    reader = member_with(makerspace, "vapi-sm", MakerspaceMembership.Role.SPACE_MANAGER)
    audit.record(reader, "audit.page", makerspace=makerspace, target=makerspace)
    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client_for(reader), makerspace, {"action": "audit.page"})
    assert response.status_code == 202
    assert response.data["state"] == "QUEUED" and response.data["deduplicated"] is False
    assert response.data["status_url"] == _url(makerspace, response.data["id"])
    run = AuditVerificationRun.objects.get(pk=response.data["id"])
    assert run.action_filter == "audit.page" and run.requested_by == reader
    assert AuditLog.objects.filter(action="audit.verification_requested").count() == 1
    assert _no_task == [run.pk]


def test_same_filters_deduplicate_and_different_filters_are_busy():
    makerspace = space("vapi-dedupe")
    client = client_for(member_with(makerspace, "vapi-dd", MakerspaceMembership.Role.SPACE_MANAGER))
    first = _post(client, makerspace, {"action": "x.y"})
    again = _post(client, makerspace, {"action": "x.y"})
    other = _post(client, makerspace, {"action": "other.action"})
    assert again.status_code == 202 and again.data["deduplicated"] is True
    assert again.data["id"] == first.data["id"]
    assert other.status_code == 409 and other.data["code"] == "audit_verification_busy"


def test_a_stale_active_run_is_timed_out_before_admission():
    makerspace = space("vapi-stale")
    client = client_for(member_with(makerspace, "vapi-st", MakerspaceMembership.Role.SPACE_MANAGER))
    first = _post(client, makerspace, {"action": "a.b"})
    # Events are immutable, so move the clock rather than the row.
    later = timezone.now() + timedelta(seconds=runs.HARD_TIME_LIMIT + runs.STALE_GRACE_SECONDS + 5)
    runs.close_stale_runs(makerspace.pk, now=later)
    latest = runs.latest_event(AuditVerificationRun.objects.get(pk=first.data["id"]))
    assert latest.state == State.TIMED_OUT and latest.failure_code == "stale_run"
    second = _post(client, makerspace, {"action": "other.b"})
    assert second.status_code == 202 and second.data["deduplicated"] is False


def test_bounds_refuse_without_creating_a_run(monkeypatch):
    makerspace = space("vapi-bounds")
    client = client_for(member_with(makerspace, "vapi-bd", MakerspaceMembership.Role.SPACE_MANAGER))
    monkeypatch.setattr(runs, "MAX_ROWS", 1)
    for _ in range(2):
        audit.record(None, "audit.page", makerspace=makerspace, target=makerspace)
    narrow = _post(client, makerspace)
    assert narrow.status_code == 400 and narrow.data["code"] == "narrow_audit_range"
    monkeypatch.setattr(runs, "MAX_ROWS", 10_000)
    monkeypatch.setattr(runs, "MAX_ANCHOR_READS", 2)
    large = _post(client, makerspace)
    assert large.status_code == 400 and large.data["code"] == "audit_verification_scope_too_large"
    assert not AuditVerificationRun.objects.filter(makerspace=makerspace).exists()


@pytest.mark.parametrize(
    "body",
    [{"actor": 0}, {"start": "nope"}, {"start": "2024-01-01T00:00:00Z", "end": "2025-06-01T00:00:00Z"}],
)
def test_malformed_filters_are_400(body):
    makerspace = space("vapi-bad")
    client = client_for(member_with(makerspace, "vapi-bad", MakerspaceMembership.Role.SPACE_MANAGER))
    assert _post(client, makerspace, body).status_code == 400


def test_scope_inventory_custom_and_org_readers_allowed_others_404():
    makerspace, other = space("vapi-scope"), space("vapi-scope-other")
    allowed = [
        member_with(makerspace, "vapi-im", MakerspaceMembership.Role.INVENTORY_MANAGER),
        custom_role_member(makerspace, "vapi-cr", {rbac.Action.VIEW_AUDIT}),
        org_auditor(makerspace, "vapi-org"),
    ]
    for reader in allowed:
        assert client_for(reader).get(_url(makerspace)).status_code == 200, reader.username
    outsider = member_with(other, "vapi-out", MakerspaceMembership.Role.SPACE_MANAGER)
    no_audit = custom_role_member(makerspace, "vapi-none", set())
    assert client_for(outsider).get(_url(makerspace)).status_code == 404
    assert _post(client_for(no_audit), makerspace).status_code == 404


def test_hidden_and_archived_makerspaces_are_404_for_a_superadmin():
    root = superadmin("vapi-root")
    hidden, archived = space("vapi-hidden"), space("vapi-archived")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    assert client_for(root).get(_url(hidden)).status_code == 404
    assert _post(client_for(root), archived).status_code == 404


def test_detail_is_aggregate_only_for_staff_and_diagnostic_for_superusers():
    makerspace = space("vapi-detail")
    staff = member_with(makerspace, "vapi-staff", MakerspaceMembership.Role.SPACE_MANAGER)
    run_id = _post(client_for(staff), makerspace).data["id"]
    staff_view = client_for(staff).get(_url(makerspace, run_id))
    root_view = client_for(superadmin("vapi-detail-root")).get(_url(makerspace, run_id))
    assert staff_view.status_code == 200 and staff_view.data["terminal"] is False
    assert {"failure_code", "first_audit_log_id", "first_batch_seq"}.isdisjoint(staff_view.data)
    assert {"failure_code", "first_audit_log_id", "first_batch_seq"} <= set(root_view.data)
    assert set(staff_view.data["coverage"]) >= {"row_count", "chain_status", "anchor_status"}
    listing = client_for(staff).get(_url(makerspace))
    assert listing.data["count"] == 1 and listing.data["results"][0]["id"] == run_id
    other = space("vapi-detail-other")
    assert client_for(staff).get(_url(other, run_id)).status_code == 404


def test_post_is_throttled(settings):
    rates = dict(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
    rates["audit_verification"] = "1/hour"
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates}
    from rest_framework.throttling import ScopedRateThrottle

    ScopedRateThrottle.THROTTLE_RATES = rates
    makerspace = space("vapi-throttle")
    client = client_for(member_with(makerspace, "vapi-th", MakerspaceMembership.Role.SPACE_MANAGER))
    try:
        assert _post(client, makerspace).status_code == 202
        assert _post(client, makerspace).status_code == 429
    finally:
        from rest_framework.settings import api_settings

        ScopedRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
