import csv
import json

import pytest

from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.tenant_migration.row_closure_helpers import create_row_closure_scenario

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def closure_archive():
    with enabled_encryption():
        actor = make_user("row-closure-export")
        source = make_space("row-closure-export")
        with portable_import_case(
            source,
            actor,
            prepare_source=create_row_closure_scenario,
        ) as case:
            yield case


def _rows(case, path):
    with (case.root / path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _references(case):
    path = case.root / "migration" / "external_references.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _reference(case, source, field_name):
    return next(
        item
        for item in _references(case)
        if item["source_model_label"] == source._meta.label
        and item["source_object_id"] == str(source.pk)
        and item["field_name"] == field_name
    )


def test_moved_asset_edges_are_dropped_or_nulled_with_anchored_provenance(
    closure_archive,
):
    case = closure_archive
    scenario = case.source_data
    links = {row["id"]: row for row in _rows(case, "lending/request_item_assets.csv")}
    assert links[str(scenario.present_link.pk)]["asset_id"] == str(
        scenario.present_asset.pk
    )
    assert links[str(scenario.moved_link.pk)]["asset_id"] == ""

    moved_link_ref = _reference(case, scenario.moved_link, "asset")
    assert moved_link_ref["target_model_label"] == "hardware_requests.HardwareRequestItem"
    assert moved_link_ref["target_object_id"] == str(scenario.request_item.pk)
    assert moved_link_ref["snapshot"] == {
        "source_id": scenario.moved_asset.pk,
        "target_model_label": "inventory.InventoryAsset",
        "state": "external",
        "label": "Transferred drill / MOVED-AWAY",
    }

    adjustments = {
        row["reason"]: row
        for row in _rows(case, "operations/inventory_adjustments.csv")
    }
    assert adjustments["Moved asset history"]["asset_id"] == ""
    assert adjustments["Originally no asset"]["asset_id"] == ""
    moved_adjustment_ref = _reference(case, scenario.moved_adjustment, "asset")
    assert moved_adjustment_ref["target_object_id"] == str(
        scenario.moved_adjustment.pk
    )
    # Matched on the model label as well as the id: a source pk is unique only WITHIN
    # a model, so an id-only predicate matches an unrelated model's row of the same pk
    # and reports provenance that was never written for this adjustment.
    assert not any(
        item["source_model_label"] == "operations.InventoryAdjustment"
        and item["source_object_id"] == str(scenario.blank_adjustment.pk)
        and item["field_name"] == "asset"
        for item in _references(case)
    )


def test_rebound_qr_is_inert_for_scans_and_loan_reference_lists(closure_archive):
    case = closure_archive
    scenario = case.source_data
    qr_rows = {row["id"]: row for row in _rows(case, "inventory/qr_mappings.csv")}
    assert qr_rows[str(scenario.present_qr.pk)]["target_id"] == str(
        scenario.present_asset.pk
    )
    assert qr_rows[str(scenario.rebound_qr.pk)]["target_type"] == "external_asset"
    assert qr_rows[str(scenario.rebound_qr.pk)]["target_id"] == "0"
    assert _reference(case, scenario.rebound_qr, "target_type+target_id")[
        "snapshot"
    ]["source_id"] == scenario.moved_asset.pk

    scan = next(
        row
        for row in _rows(case, "lending/qr_scan_events.csv")
        if row["id"] == str(scenario.rebound_scan.pk)
    )
    assert scan["qr_code_id"] == ""
    scan_ref = _reference(case, scenario.rebound_scan, "qr_code")
    assert scan_ref["target_model_label"] == "hardware_requests.HardwareRequest"
    assert scan_ref["target_object_id"] == str(case.request.pk)

    loan = _rows(case, "lending/direct_and_self_checkout_loans.csv")[0]
    assert json.loads(loan["asset_ids"]) == [scenario.present_asset.pk]
    assert json.loads(loan["qr_ids"]) == [scenario.present_qr.pk]
    assert _reference(case, scenario.loan, "asset_ids")["snapshot"]["references"][
        0
    ]["source_id"] == scenario.moved_asset.pk
    assert _reference(case, scenario.loan, "qr_ids")["snapshot"]["references"][0][
        "source_id"
    ] == scenario.rebound_qr.pk


def test_inbound_transfer_and_dependents_export_as_typed_provenance(closure_archive):
    case = closure_archive
    scenario = case.source_data
    transfer = next(
        row
        for row in _rows(case, "transfers/transfers.csv")
        if row["id"] == str(scenario.inbound_transfer.pk)
    )
    assert transfer["destination_makerspace_id"] == str(case.membership.makerspace_id)
    transfer_ref = _reference(case, scenario.inbound_transfer, "inbound_transfer")
    assert transfer_ref["snapshot"]["reason"] == "Inbound from another owner"
    assert transfer_ref["snapshot"]["destination"]["slug"] == case.membership.makerspace.slug

    line_ref = _reference(case, scenario.inbound_line, "inbound_transfer")
    assert line_ref["snapshot"]["transfer_source_id"] == scenario.inbound_transfer.pk
    assert line_ref["snapshot"]["notes"] == "Foreign-owned line"

    adjustment = next(
        row
        for row in _rows(case, "operations/inventory_adjustments.csv")
        if row["id"] == str(scenario.inbound_adjustment.pk)
    )
    assert adjustment["transfer_id"] == ""
    assert _reference(case, scenario.inbound_adjustment, "transfer")["snapshot"][
        "source_id"
    ] == scenario.inbound_transfer.pk
