"""UX projections and archive undo publish usable authenticated API contracts."""
import pytest
from django.urls import path
from drf_spectacular.generators import SchemaGenerator

from apps.admin_api.views_inventory_products import InventoryDetailView
from apps.admin_api.views_inventory_export import InventoryExportView
from apps.admin_api.views_setup_state import MakerspaceSetupStateView
from apps.maintenance.views_overdue import OverdueMaintenanceListView
from apps.makerspaces.member_card_views import MemberCardOwnView


@pytest.fixture(scope="module")
def ux_schema():
    return SchemaGenerator(patterns=[
        path("api/v1/admin/makerspace/<int:makerspace_id>/setup-state", MakerspaceSetupStateView.as_view()),
        path("api/v1/admin/makerspace/<int:makerspace_id>/maintenance-overdue", OverdueMaintenanceListView.as_view()),
        path("api/v1/member/makerspaces/<int:makerspace_id>/member-card", MemberCardOwnView.as_view()),
        path("api/v1/admin/inventory/<int:pk>", InventoryDetailView.as_view()),
        path("api/v1/admin/makerspace/<int:makerspace_id>/inventory/export", InventoryExportView.as_view()),
    ]).get_schema(request=None, public=True)


def resolve(schema, node):
    if "$ref" in node:
        return schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]
    return node


def test_ux_read_routes_document_authentication_and_actual_response_shapes(ux_schema):
    schema = ux_schema
    paths = schema["paths"]
    prefix = "/api/v1/admin/makerspace/{makerspace_id}/"
    setup = paths[prefix + "setup-state"]["get"]
    overdue = paths[prefix + "maintenance-overdue"]["get"]
    card = paths["/api/v1/member/makerspaces/{makerspace_id}/member-card"]["get"]
    for operation in (setup, overdue, card):
        assert operation["security"]
        assert "requestBody" not in operation
        assert {"200", "401", "403", "404"} <= set(operation["responses"])
    for operation in (overdue, card):
        assert "400" in operation["responses"]
    setup_body = resolve(schema, setup["responses"]["200"]["content"]["application/json"]["schema"])
    assert set(setup_body["properties"]) == {"profile_set", "hours_set", "first_item_added", "staff_invited", "modules_chosen"}
    page = resolve(schema, overdue["responses"]["200"]["content"]["application/json"]["schema"])
    assert {"count", "next", "previous", "results"} <= set(page["properties"])
    row = resolve(schema, page["properties"]["results"]["items"])
    assert {"id", "machine_id", "machine_name", "description", "next_due"} == set(row["properties"])
    own = resolve(schema, card["responses"]["200"]["content"]["application/json"]["schema"])
    assert own["properties"]["qr_image"]["nullable"] is True
    assert not {"photo_object_key", "qr_payload"} & set(own["properties"])


def test_archive_compensation_documents_partial_input_and_failures(ux_schema):
    operation = ux_schema["paths"]["/api/v1/admin/inventory/{id}"]["patch"]
    assert operation["security"]
    assert {"200", "400", "401", "403", "404", "423"} <= set(operation["responses"])
    body = resolve(ux_schema, operation["requestBody"]["content"]["application/json"]["schema"])
    assert "is_archived" in body["properties"]
    assert not body.get("required")
    export = ux_schema["paths"]["/api/v1/admin/makerspace/{makerspace_id}/inventory/export"]["get"]
    parameters = {parameter["name"]: parameter for parameter in export["parameters"]}
    assert set(parameters["archived"]["schema"]["enum"]) == {"true", "false", "all"}
    assert set(parameters["out_of_stock"]["schema"]["enum"]) == {"true", "false"}
