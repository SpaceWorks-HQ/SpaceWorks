from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.urls import reverse
from django.utils import timezone

from apps.evidence.models import EvidencePhoto
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.operations.models import ReportMetricRollup, ReportRollupCursor
from apps.operations.report_coverage import REPORT_MODULE_COVERAGE, check_report_module_coverage
from apps.operations.report_registry import report_definition
from apps.operations.report_rollups import finalize_evidence_rollups
from apps.operations.reports_inventory_control import build_inventory_control
from apps.evidence.reports import build_evidence_compliance
from apps.makerspaces.module_registry import MODULE_KEYS
from tests.return_helpers import authenticated_client, make_member, make_space


pytestmark = pytest.mark.django_db


def test_every_module_has_valid_report_coverage():
    assert set(REPORT_MODULE_COVERAGE) == set(MODULE_KEYS)
    assert check_report_module_coverage() == []
    assert report_definition("import-quality").required_action == "edit_inventory"
    assert report_definition("communications-health").required_action == "manage_makerspace"
    assert report_definition("evidence-compliance").required_modules == ("evidence_uploads",)
    assert report_definition("loan-throughput").grains == ("day", "month")


def test_rollup_dimensions_reject_person_identifiers():
    space = make_space("report-rollup-dimensions")
    rollup = ReportMetricRollup(
        makerspace=space, source_module="evidence_uploads",
        report_key="evidence-compliance", metric_key="created_count",
        bucket_start=timezone.now(), grain=ReportMetricRollup.Grain.DAY,
        dimension_key="requester_id=42", dimensions={"requester_id": 42},
        value=1, sample_count=1, revision=1, source_cutoff=timezone.now(),
        checksum="a" * 64,
    )
    with pytest.raises(ValidationError):
        rollup.full_clean()


def test_catalog_exposes_disabled_source_without_reading_its_rows():
    space = make_space("report-catalog-modules")
    manager = make_member("report-catalog-manager", space)
    space.enabled_modules.remove("bulk_import")
    space.save(update_fields=["enabled_modules"])

    response = authenticated_client(manager).get(
        reverse("report-catalog", args=[space.id])
    )

    assert response.status_code == 200, response.data
    definitions = {row["key"]: row for row in response.data["results"]}
    assert definitions["import-quality"]["available"] is False
    assert definitions["loan-throughput"]["available"] is True

    space.enabled_modules.append("bulk_import")
    space.save(update_fields=["enabled_modules"])
    enabled = authenticated_client(manager).get(
        reverse("report-catalog", args=[space.id])
    )
    assert enabled.status_code == 200, enabled.data
    enabled_definitions = {row["key"]: row for row in enabled.data["results"]}
    assert enabled_definitions["import-quality"]["available"] is True


def test_reports_module_controls_catalog_read_and_export_on_both_sides():
    space = make_space("reports-off-contract")
    manager = make_member("reports-off-manager", space)
    client = authenticated_client(manager)
    catalog_url = reverse("report-catalog", args=[space.id])
    read_url = reverse("analytics-generic", args=[space.id, "loan-throughput"])
    export_url = reverse("report-export", args=[space.id, "loan-throughput"])
    machine_report_url = reverse("admin-makerspace-machine-service-report", args=[space.id])

    space.enabled_modules.remove("reports")
    space.save(update_fields=["enabled_modules"])
    assert client.get(catalog_url).status_code == 400
    assert client.get(read_url).status_code == 400
    assert client.get(export_url, {"format": "csv"}).status_code == 400
    assert client.get(machine_report_url).status_code == 400

    space.enabled_modules.append("reports")
    space.save(update_fields=["enabled_modules"])
    assert client.get(catalog_url).status_code == 200
    assert client.get(read_url).status_code == 200
    assert client.get(export_url, {"format": "csv"}).status_code == 200
    assert client.get(machine_report_url).status_code == 200


def test_composite_inventory_report_gates_retained_asset_rows():
    space = make_space("report-inventory-composite")
    product = InventoryProduct.objects.create(
        makerspace=space, name="Retained unit", total_quantity=1, available_quantity=1
    )
    InventoryAsset.objects.create(
        makerspace=space, product=product, asset_tag="RETAINED-REPORT-1"
    )
    space.enabled_modules.remove("asset_units")
    space.save(update_fields=["enabled_modules"])

    hidden = build_inventory_control(space.id)
    assert not [row for row in hidden.records if row["module_key"] == "asset_units"]

    space.enabled_modules.append("asset_units")
    space.save(update_fields=["enabled_modules"])
    visible = build_inventory_control(space.id)
    assert sum(row["count"] for row in visible.records if row["module_key"] == "asset_units") == 1


def test_evidence_rollup_revisions_are_append_only_and_retention_safe():
    space = make_space("report-rollup-history")
    manager = make_member("report-rollup-manager", space)
    for index in range(4):
        EvidencePhoto.objects.create(
            makerspace=space, evidence_type=EvidencePhoto.EvidenceType.ISSUE,
            object_key=f"evidence/report-rollup-history/issue-{index}.jpg",
            content_type="image/jpeg", size_bytes=321, uploaded_by=manager,
        )
    through = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    finalize_evidence_rollups(space, through=through, actor=manager)
    before = build_evidence_compliance(space.id)
    created = ReportMetricRollup.objects.get(
        makerspace=space, metric_key="created_count", revision=1
    )
    cursor = ReportRollupCursor.objects.get(
        makerspace=space, source_module="evidence_uploads"
    )
    assert cursor.rolled_through == through
    assert before.records[0]["created_count"] == 4

    with pytest.raises(DatabaseError), transaction.atomic():
        ReportMetricRollup.objects.filter(pk=created.pk).update(value=99)
    with pytest.raises(DatabaseError), transaction.atomic():
        ReportMetricRollup.objects.filter(pk=created.pk).delete()

    with transaction.atomic():
        with connection.cursor() as cursor_handle:
            cursor_handle.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        EvidencePhoto.objects.filter(makerspace=space).delete()

    after = build_evidence_compliance(space.id)
    assert after.records == before.records


def test_late_evidence_attachment_appends_a_higher_revision():
    space = make_space("report-rollup-revision")
    manager = make_member("report-rollup-revision-manager", space)
    evidence = EvidencePhoto.objects.create(
        makerspace=space, evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key="evidence/report-rollup-revision/issue.jpg", uploaded_by=manager,
    )
    through = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    finalize_evidence_rollups(space, through=through, actor=manager)

    from apps.hardware_requests.models import HardwareRequest

    request = HardwareRequest.objects.create(
        makerspace=space, requester=manager, requester_username=manager.username,
        issue_evidence=evidence,
    )
    assert request.issue_evidence_id == evidence.id
    finalize_evidence_rollups(space, through=through, actor=manager)

    revisions = list(ReportMetricRollup.objects.filter(
        makerspace=space, metric_key="attached_count"
    ).order_by("revision").values_list("revision", "value"))
    assert revisions == [(1, 0), (2, 1)]
