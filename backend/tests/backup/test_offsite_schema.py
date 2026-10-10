"""Generate the offsite API contract without writing the coordinator's snapshots."""

import pytest
from django.urls import include, path
from drf_spectacular.generators import SchemaGenerator

pytestmark = pytest.mark.django_db


def test_offsite_routes_have_authenticated_request_response_and_error_schemas():
    schema = SchemaGenerator(patterns=[
        path("api/v1/admin/", include("apps.admin_api.urls_platform")),
    ]).get_schema(request=None, public=True)
    base = "/api/v1/admin/platform/backup-destinations"
    operations = {
        base: ("get", "post"),
        base + "/{destination_id}": ("get", "patch"),
        base + "/{destination_id}/retire": ("post",),
        base + "/{destination_id}/test": ("post",),
        base + "/{destination_id}/uploads": ("get",),
        base + "/push": ("post",),
        "/api/v1/admin/platform/backups/{archive_id}/rehydrate": ("post",),
    }
    for route, methods in operations.items():
        for method in methods:
            operation = schema["paths"][route][method]
            assert operation["security"], (route, method)
            assert {"401", "403"} <= operation["responses"].keys()
            success = next(key for key in operation["responses"] if key.startswith("2"))
            assert operation["responses"][success]["content"]["application/json"]["schema"]
    for route in (base, base + "/{destination_id}/uploads"):
        operation = schema["paths"][route]["get"]
        assert any(parameter["name"] == "page" for parameter in operation["parameters"])
        ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        page = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        assert {"count", "next", "previous", "results"} <= page["properties"].keys()
    destination_ref = schema["paths"][base]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    destination = schema["components"]["schemas"][destination_ref.rsplit("/", 1)[-1]]
    assert destination["properties"]["access_key_id"]["writeOnly"]
    assert destination["properties"]["secret_access_key"]["writeOnly"]
    for route, method in ((base, "post"), (base + "/{destination_id}", "patch"),
                          ("/api/v1/admin/platform/backups/{archive_id}/rehydrate", "post")):
        assert "requestBody" in schema["paths"][route][method]
        assert "400" in schema["paths"][route][method]["responses"]
    assert "503" in schema["paths"][base + "/push"]["post"]["responses"]
    recipients = schema["paths"]["/api/v1/admin/makerspace/{makerspace_id}/archive-recipients"]["get"]
    assert "400" in recipients["responses"]
