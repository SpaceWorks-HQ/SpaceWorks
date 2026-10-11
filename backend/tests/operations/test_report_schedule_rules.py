"""Conditions and recipients use the existing idempotent, private-link delivery path."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.operations import report_schedule_services as services
from apps.operations.models import ReportDelivery, ReportSchedule
from apps.operations.report_registry import REPORT_REGISTRY
from apps.operations.report_schedule_rules import condition_matches, recipient_emails, validate_condition
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def schedule(space, actor, **extra):
    return ReportSchedule.objects.create(makerspace=space, created_by=actor, report_key="most-lent",
        next_run_at=timezone.now() - timedelta(minutes=1), **extra)


def reader(space, name, *, actions=None):
    user = make_user(name, access_status="active")
    role = MakerspaceRole.objects.create(makerspace=space, name=name, slug=name,
                                        granted_actions=actions or [rbac.Action.VIEW_AUDIT])
    membership = MakerspaceMembership.objects.create(makerspace=space, user=user, role="custom", assigned_role=role)
    return user, membership, role


@pytest.fixture
def transport(monkeypatch):
    stored, sent = [], []
    monkeypatch.setattr(services, "store_report_object", lambda *args: stored.append(args))
    monkeypatch.setattr(services, "signed_download_url", lambda key: f"https://private.test/{key}")
    monkeypatch.setattr(services, "delete_report_object", lambda key: None)
    monkeypatch.setattr(services.reports, "report_rows", lambda *args, **kwargs: [["product_name", "times_lent", "total_quantity_lent"], ["Drill", 2, 4]])
    def send(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(status="sent")
    monkeypatch.setattr(services, "dispatch_email", send)
    return stored, sent


@pytest.mark.parametrize("operator,value,expected", [("gt", "3", True), ("gte", "4", True), ("lt", "4", False), ("lte", "4", True), ("eq", "4", True)])
def test_condition_threshold_sums_numeric_rows(operator, value, expected):
    condition = {"metric": "times_lent", "operator": operator, "value": value}
    assert condition_matches(condition, [["times_lent"], [1], [3]]) is expected


def test_non_empty_ignores_header_and_currency_threshold_never_sums_currencies():
    assert condition_matches({"non_empty": True}, [["count"]]) is False
    assert condition_matches({"non_empty": True}, [["count"], [0]]) is True
    rows = [["currency", "mrr"], ["usd", "10.00"], ["eur", "40.00"]]
    condition = {"metric": "mrr", "operator": "gt", "value": "20"}
    with pytest.raises(ValueError, match="currency"):
        condition_matches(condition, rows)
    assert condition_matches({**condition, "currency": "usd"}, rows) is False
    assert condition_matches({**condition, "currency": "eur"}, rows) is True


@pytest.mark.parametrize("value", [[], {"metric": "times_lent"}, {"metric": "product_name", "operator": "gt", "value": "1"}, {"metric": "times_lent", "operator": "exec", "value": "1"}, {"metric": "times_lent", "operator": "gt", "value": "NaN"}, {"sql": "select"}])
def test_condition_contract_rejects_invalid_or_non_numeric_metrics(value):
    with pytest.raises(ValidationError):
        validate_condition(value, REPORT_REGISTRY["most-lent"])


def test_unmet_condition_advances_once_audits_skip_and_never_creates_an_object(transport):
    space = make_space("schedule-condition")
    actor = make_member("schedule-condition-manager", space)
    row = schedule(space, actor, recipient_emails=["external@example.test"], condition={"metric": "times_lent", "operator": "gt", "value": "9"})
    now = timezone.now()
    assert services.run_report_schedules(now=now) == {"delivered": 0, "failed": 0, "skipped": 1}
    assert services.run_report_schedules(now=now) == {"delivered": 0, "failed": 0, "skipped": 0}
    assert not ReportDelivery.objects.filter(schedule=row).exists()
    assert transport == ([], [])
    row.refresh_from_db()
    assert row.next_run_at > now
    assert AuditLog.objects.filter(action="report_schedule.skipped", meta__reason="condition_not_met").exists()


def test_live_role_and_action_recipients_stop_after_revocation_and_deduplicate(transport):
    space = make_space("schedule-role")
    actor = make_member("schedule-role-manager", space)
    user, membership, role = reader(space, "schedule-role-reader")
    other = make_space("schedule-role-foreign")
    foreign, _, _ = reader(other, "schedule-role-outsider")
    row = schedule(space, actor, recipient_roles=[role.slug], recipient_actions=[rbac.Action.VIEW_AUDIT],
                   condition={"non_empty": True, "metric": "times_lent", "operator": "gt", "value": "1"})
    now = timezone.now()
    services.run_report_schedules(now=now)
    sent = transport[1]
    emails = [item["to_email"] for item in sent]
    assert emails.count(user.email) == 1
    assert foreign.email not in emails
    assert all("https://private.test/reports/" in item["text_body"] for item in sent)
    assert services.run_report_schedules(now=now)["delivered"] == 0
    membership.status = "revoked"
    membership.save(update_fields=["status"])
    sent.clear()
    row.refresh_from_db()
    services.run_report_schedules(now=row.next_run_at + timedelta(seconds=1))
    assert user.email not in [item["to_email"] for item in sent]


def test_recipient_resolution_respects_opt_out_restriction_and_report_authority():
    space = make_space("schedule-recipient-floor")
    actor = make_member("schedule-recipient-floor-manager", space)
    user, membership, role = reader(space, "schedule-recipient-floor-reader")
    row = schedule(space, actor, recipient_roles=[role.slug])
    definition = REPORT_REGISTRY["most-lent"]
    assert recipient_emails(row, definition) == [user.email]
    membership.receives_notifications = False
    membership.save(update_fields=["receives_notifications"])
    assert recipient_emails(row, definition) == []
    membership.receives_notifications = True
    membership.save(update_fields=["receives_notifications"])
    user.access_status = "restricted"
    user.save(update_fields=["access_status"])
    assert recipient_emails(row, definition) == []
    user.access_status = "active"
    user.save(update_fields=["access_status"])
    assert recipient_emails(row, REPORT_REGISTRY["membership-revenue"]) == []


def test_schedule_api_validates_role_tenant_action_and_metric_and_allows_dynamic_only():
    space, other = make_space("schedule-rules-api"), make_space("schedule-rules-api-other")
    actor = make_member("schedule-rules-api-manager", space)
    _, _, role = reader(space, "schedule-rules-api-role")
    _, _, foreign = reader(other, "schedule-rules-api-foreign")
    client = authenticated_client(actor)
    path = f"/api/v1/admin/makerspaces/{space.pk}/report-schedules"
    payload = {"report_key": "most-lent", "recipient_roles": [role.slug],
               "condition": {"non_empty": True, "metric": "times_lent", "operator": "gt", "value": "0"}}
    created = client.post(path, payload, format="json")
    assert created.status_code == 201, created.data
    assert created.data["recipient_roles"] == [role.slug]
    assert client.post(path, {**payload, "recipient_roles": [foreign.slug]}, format="json").status_code == 400
    assert client.post(path, {**payload, "recipient_actions": ["made_up"]}, format="json").status_code == 400
    assert client.post(path, {**payload, "condition": {"metric": "product_name", "operator": "gt", "value": "1"}}, format="json").status_code == 400
    stranger = make_member("schedule-rules-api-stranger", other)
    assert authenticated_client(stranger).get(path).status_code == 404


def test_legacy_explicit_local_staff_address_stops_receiving_after_revocation():
    space = make_space("schedule-legacy-email")
    actor = make_member("schedule-legacy-email-manager", space)
    user, membership, _role = reader(space, "schedule-legacy-email-reader")
    row = schedule(space, actor, recipient_emails=[user.email, "external@example.test"])
    membership.status = "revoked"
    membership.save(update_fields=["status"])
    assert recipient_emails(row, REPORT_REGISTRY["most-lent"]) == ["external@example.test"]


def test_new_schedule_staff_targets_use_live_selectors_instead_of_addresses():
    space = make_space("schedule-no-frozen-staff")
    actor = make_member("schedule-no-frozen-manager", space)
    user, _membership, role = reader(space, "schedule-no-frozen-reader")
    client = authenticated_client(actor)
    path = f"/api/v1/admin/makerspaces/{space.pk}/report-schedules"
    response = client.post(path, {"report_key": "most-lent", "recipient_emails": [user.email]}, format="json")
    assert response.status_code == 400
    assert client.post(path, {"report_key": "most-lent", "recipient_roles": [role.slug]}, format="json").status_code == 201


def test_non_empty_condition_skip_uses_the_same_schedule_path(monkeypatch, transport):
    space = make_space("schedule-empty")
    actor = make_member("schedule-empty-manager", space)
    schedule(space, actor, recipient_actions=[rbac.Action.VIEW_AUDIT], condition={"non_empty": True})
    monkeypatch.setattr(services.reports, "report_rows", lambda *args, **kwargs: [["product_name", "times_lent", "total_quantity_lent"]])
    assert services.run_report_schedules()["skipped"] == 1
    assert not ReportDelivery.objects.exists()
    assert transport == ([], [])


def test_legacy_staff_email_can_be_retained_on_edit_but_new_staff_addresses_are_refused():
    space = make_space("schedule-legacy-edit")
    actor = make_member("schedule-legacy-edit-manager", space)
    original, _, _ = reader(space, "schedule-legacy-original")
    added, _, _ = reader(space, "schedule-legacy-added")
    row = schedule(space, actor, recipient_emails=[original.email])
    client = authenticated_client(actor)
    path = f"/api/v1/admin/report-schedules/{row.pk}"
    changed = client.patch(path, {"recipient_emails": [original.email], "condition": {"non_empty": True}}, format="json")
    assert changed.status_code == 200, changed.data
    assert client.patch(path, {"recipient_emails": [original.email, added.email]}, format="json").status_code == 400


@pytest.mark.parametrize("filters", [{"months": 6}, {"status": "pending"}, {"subject_type": "membership_term"}])
def test_schedule_rejects_filters_its_report_would_ignore(filters):
    space = make_space("schedule-filter-contract")
    actor = make_member("schedule-filter-contract-manager", space)
    response = authenticated_client(actor).post(f"/api/v1/admin/makerspaces/{space.pk}/report-schedules",
        {"report_key": "most-lent", "recipient_actions": [rbac.Action.VIEW_AUDIT], "filters": filters}, format="json")
    assert response.status_code == 400, response.data
    assert not ReportSchedule.objects.exists()


def test_presign_failure_retains_stored_key_for_expiry_cleanup_and_omits_secrets(monkeypatch, transport, caplog):
    space = make_space("schedule-presign-failure")
    actor = make_member("schedule-presign-failure-manager", space)
    row = schedule(space, actor, recipient_actions=[rbac.Action.VIEW_AUDIT])
    def failed_url(key):
        raise RuntimeError("SECRET-PRESIGN-CREDENTIAL")
    monkeypatch.setattr(services, "signed_download_url", failed_url)
    delivery = services.run_schedule(row.pk)
    assert delivery.status == "failed" and delivery.error == "build:RuntimeError"
    assert delivery.object_key == transport[0][0][0]
    assert delivery.expires_at is not None
    assert "SECRET-PRESIGN-CREDENTIAL" not in caplog.text
    deleted = []
    monkeypatch.setattr(services, "delete_report_object", deleted.append)
    services._sweep_expired(row, delivery.expires_at + timedelta(seconds=1))
    assert deleted == [delivery.object_key]


def test_schedule_selector_fields_cannot_restore_source_disclosure_authority():
    from apps.tenant_migration.tenant_dump_catalog import FIELD_POLICIES
    from apps.tenant_migration.tenant_dump_types import AuthorityDisposition
    from apps.tenant_migration.target_projection_rows import ROW_POLICIES

    for field in ("condition", "recipient_roles", "recipient_actions"):
        assert FIELD_POLICIES[("operations.ReportSchedule", field)].dispositions == (AuthorityDisposition.DROP,)
    assert ROW_POLICIES["operations.ReportSchedule"].disposition.value == "drop"


def test_expired_delivery_retries_a_failed_object_delete(monkeypatch):
    space = make_space("schedule-expiry-retry")
    actor = make_member("schedule-expiry-retry-manager", space)
    row = schedule(space, actor, recipient_actions=[rbac.Action.VIEW_AUDIT])
    delivery = ReportDelivery.objects.create(schedule=row, object_key=f"reports/{space.pk}/old.csv",
        expires_at=timezone.now() - timedelta(seconds=1), status="sent")
    monkeypatch.setattr(services, "delete_report_object", lambda key: False)
    services._sweep_expired(row, timezone.now())
    delivery.refresh_from_db()
    assert delivery.object_key
    removed = []
    monkeypatch.setattr(services, "delete_report_object", lambda key: removed.append(key) or True)
    services._sweep_expired(row, timezone.now())
    assert removed == [delivery.object_key]
    delivery.refresh_from_db()
    assert delivery.object_key == ""


def test_report_storage_delete_reports_failure_without_exposing_storage_errors(monkeypatch):
    from apps.evidence.storage import StorageUnavailable
    from apps.operations import report_delivery_storage

    def unavailable(key):
        raise StorageUnavailable("SECRET-STORAGE-CREDENTIAL")
    monkeypatch.setattr(report_delivery_storage.storage, "delete_object_strict", unavailable)
    assert report_delivery_storage.delete_report_object("reports/1/old.csv") is False
