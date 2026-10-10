from uuid import uuid4

import pytest
from django.test import RequestFactory
from django.urls import resolve
from drf_spectacular.generators import SchemaGenerator

from apps.devices.checks import check_device_route_registry
from apps.devices.models import LabelPrintCommand, LabelPrintResult
from apps.devices.services_commands import lease_command
from apps.makerspaces.origin_scope_routes import request_route_targets
from tests.devices.helpers_labels import label_case, signed_call, staff_path
from tests.module_helpers import disable_module
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("key", ["devices", "qr_print_batches"])
def test_module_off_returns_400_on_staff_content_and_results(key):
    case = label_case(f"label-module-{key}", acknowledged=True)
    disable_module(case["space"], key)
    response = case["client"].post(staff_path(case),
        {"device_id": str(case["device"].pk), "request_id": str(uuid4())}, format="json")
    assert response.status_code == 400
    assert signed_call(case, "devices:device-label-command-content", method="GET").status_code == 400
    assert signed_call(case, "devices:device-label-command-result", body={"operation_id": str(uuid4()),
        "outcome": "succeeded", "result_code": "ok"}).status_code == 400
    assert LabelPrintCommand.objects.count() == 1 and not LabelPrintResult.objects.exists()


def test_disabled_label_adapter_is_cancelled_by_generic_poll_and_never_resurrects():
    case = label_case("label-module-cancel", sent=True)
    disable_module(case["space"], "qr_print_batches")
    assert lease_command(case["principal"]) is None
    case["label"].refresh_from_db()
    assert case["label"].command.status == "cancelled"
    case["space"].enabled_modules = sorted(set(case["space"].enabled_modules) | {"qr_print_batches"})
    case["space"].save(update_fields=["enabled_modules"])
    assert lease_command(case["principal"]) is None


def test_source_gate_refuses_all_label_writes_without_creating_receipts():
    case = label_case("label-source-gate", acknowledged=True)
    close_gate(case["space"], make_actor("label-source-gate"))
    response = case["client"].post(staff_path(case),
        {"device_id": str(case["device"].pk), "request_id": str(uuid4())}, format="json")
    assert response.status_code == 423
    assert signed_call(case, "devices:device-label-command-content", method="GET").status_code == 423
    assert signed_call(case, "devices:device-label-command-result", body={"operation_id": str(uuid4()),
        "outcome": "succeeded", "result_code": "ok"}).status_code == 423
    assert not LabelPrintResult.objects.exists()


def test_staff_origin_scope_reads_batch_pk_and_device_registry_is_exact():
    case = label_case("label-origin")
    request = RequestFactory().get(staff_path(case))
    request.resolver_match = resolve(staff_path(case))
    _name, targets, invalid, recognized = request_route_targets(request)
    assert targets == {case["space"].pk} and recognized and not invalid
    assert check_device_route_registry(app_configs=None) == []


def test_openapi_documents_staff_send_signed_zip_and_idempotent_result():
    schema = SchemaGenerator().get_schema(public=True)
    staff = schema["paths"]["/api/v1/admin/qr-print-batches/{id}/label-commands"]
    content = schema["paths"]["/api/v1/device/label-commands/{id}/content"]["get"]
    result = schema["paths"]["/api/v1/device/label-commands/{id}/result"]["post"]
    assert {"get", "post"} <= set(staff)
    assert "application/zip" in content["responses"]["200"]["content"]
    assert result["requestBody"]["required"]
    for operation in [staff["post"], content, result]:
        assert {"400", "401", "403", "404", "409", "410", "423"} <= set(operation["responses"])
    assert content["security"] and result["security"]
