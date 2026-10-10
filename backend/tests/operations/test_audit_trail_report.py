"""The audit-trail report: projected CSV only, tenant only, never previewed or scheduled."""

import pytest

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.models import MakerspaceMembership
from apps.operations import reports_audit
from apps.operations.models import ReportSchedule
from apps.operations.org_report_scope import EXCLUDED_ORGANIZATION_REPORT_KEYS
from apps.operations.report_registry import DEPLOYMENT_AGGREGATE_REPORT_KEYS, REPORT_REGISTRY
from apps.operations.report_schedule_services import _skip_reason
from tests.audit_explorer_helpers import (
    client_for,
    custom_role_member,
    member_with,
    org_auditor,
    superadmin,
)
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db


def _export(client, space, fmt="csv", **params):
    query = "&".join([f"format={fmt}", *[f"{key}={value}" for key, value in params.items()]])
    return client.get(f"/api/v1/admin/makerspace/{space.id}/reports/audit-trail/export?{query}")


def _body(response):
    return b"".join(response.streaming_content if response.streaming else [response.content]).decode()


@pytest.fixture
def called(monkeypatch):
    calls = []
    real = reports_audit.build_audit_trail

    def spy(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(reports_audit, "build_audit_trail", spy)
    return calls


def test_definition_capabilities():
    definition = REPORT_REGISTRY["audit-trail"]
    assert definition.allowed_formats == ("csv",)
    assert not definition.schedulable and not definition.previewable
    assert not definition.deployment_aggregate
    assert definition.required_action == rbac.Action.VIEW_AUDIT
    assert "audit-trail" not in DEPLOYMENT_AGGREGATE_REPORT_KEYS
    assert "audit-trail" in EXCLUDED_ORGANIZATION_REPORT_KEYS


def test_csv_redacts_exactly_what_the_api_hides():
    space = make_space("atr-csv")
    manager = member_with(space, "atr-sm", MakerspaceMembership.Role.SPACE_MANAGER)
    audit.record(manager, "request.issued", makerspace=space, target=space,
                 meta={"box_id": 5, "evidence_id": 6, "email": "leak@example.test"})
    audit.record(manager, "never.heard_of", makerspace=space, target=space, meta={"phone": "555"})
    response = _export(client_for(manager), space)
    assert response.status_code == 200
    body = _body(response)
    assert "leak@example.test" not in body and "555" not in body
    assert '{""box_id"":5,""evidence_id"":6}' in body
    assert "Unrecognized audit action" in body


def test_filters_apply_and_xlsx_is_refused():
    space = make_space("atr-filter")
    manager = member_with(space, "atr-f", MakerspaceMembership.Role.SPACE_MANAGER)
    audit.record(manager, "audit.page", makerspace=space, target=space)
    audit.record(manager, "audit.other", makerspace=space, target=space)
    client = client_for(manager)
    body = _body(_export(client, space, action="audit.other"))
    assert "audit.other" in body and "audit.page" not in body
    assert _export(client, space, fmt="xlsx").status_code == 400
    assert _export(client, space, actor="0").status_code == 400


def test_json_preview_and_every_deployment_surface_refuse_without_the_builder(called):
    space = make_space("atr-preview")
    manager = member_with(space, "atr-p", MakerspaceMembership.Role.SPACE_MANAGER)
    root = superadmin("atr-root")
    preview = client_for(manager).get(f"/api/v1/admin/makerspace/{space.id}/analytics/audit-trail")
    aggregate = client_for(root).get("/api/v1/admin/analytics/audit-trail")
    aggregate_export = client_for(root).get("/api/v1/admin/reports/audit-trail/export?format=csv")
    catalog = client_for(root).get("/api/v1/admin/reports/catalog")
    assert preview.status_code == 404 and aggregate.status_code == 404
    assert aggregate_export.status_code == 404
    assert "audit-trail" not in {row["key"] for row in catalog.data["results"]}
    assert called == []


def test_builder_refuses_a_missing_makerspace():
    with pytest.raises(ValueError):
        reports_audit.build_audit_trail(None)


def test_view_audit_only_local_and_org_readers_can_export():
    space = make_space("atr-readers")
    for reader in (
        custom_role_member(space, "atr-custom", {rbac.Action.VIEW_AUDIT}),
        org_auditor(space, "atr-org"),
    ):
        assert _export(client_for(reader), space).status_code == 200, reader.username


def test_inventory_visible_actor_without_the_action_gets_403_and_outsider_404():
    space, other = make_space("atr-matrix"), make_space("atr-matrix-other")
    inventory_only = custom_role_member(space, "atr-inv", {rbac.Action.VIEW_INVENTORY})
    outsider = member_with(other, "atr-out", MakerspaceMembership.Role.SPACE_MANAGER)
    assert _export(client_for(inventory_only), space).status_code == 403
    assert _export(client_for(outsider), space).status_code == 404


def test_catalog_exposes_the_capabilities():
    space = make_space("atr-catalog")
    manager = member_with(space, "atr-c", MakerspaceMembership.Role.SPACE_MANAGER)
    rows = {row["key"]: row for row in client_for(manager).get(
        f"/api/v1/admin/makerspace/{space.id}/reports/catalog").data["results"]}
    assert rows["audit-trail"]["allowed_formats"] == ["csv"]
    assert rows["audit-trail"]["schedulable"] is False
    assert rows["audit-trail"]["previewable"] is False
    assert rows["most-lent"]["allowed_formats"] == ["csv", "xlsx"]


def test_schedules_refuse_create_and_a_stale_row_is_skipped():
    space = make_space("atr-sched")
    manager = member_with(space, "atr-s", MakerspaceMembership.Role.SPACE_MANAGER)
    response = client_for(manager).post(
        f"/api/v1/admin/makerspaces/{space.id}/report-schedules",
        {"report_key": "audit-trail", "format": "csv", "cadence": "daily",
         "recipient_emails": ["a@example.test"]},
        format="json",
    )
    assert response.status_code == 400
    stale = ReportSchedule(makerspace=space, report_key="audit-trail", format="csv",
                           cadence="daily", created_by=manager)
    assert _skip_reason(stale, REPORT_REGISTRY["audit-trail"]) == "report_unavailable"
    xlsx_only_bad = ReportSchedule(makerspace=space, report_key="most-lent", format="pdf",
                                   cadence="daily", created_by=manager)
    assert _skip_reason(xlsx_only_bad, REPORT_REGISTRY["most-lent"]) == "format_not_allowed"
