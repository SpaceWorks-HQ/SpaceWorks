"""Profile schemas describe partial writes, typed errors and public privacy."""

import pytest
from django.urls import path
from drf_spectacular.generators import SchemaGenerator

from apps.admin_api.views_makerspace_profile import MakerspaceProfileView
from apps.makerspaces.views import BootstrapView


@pytest.fixture(scope="module")
def profile_schema():
    return SchemaGenerator(patterns=[
        path("api/v1/admin/makerspace/<int:makerspace_id>/profile", MakerspaceProfileView.as_view()),
        path("api/v1/bootstrap", BootstrapView.as_view()),
    ]).get_schema(request=None, public=True)


def resolve(schema, node):
    if "$ref" in node:
        return schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]
    return node


def test_profile_schema_documents_partial_patch_and_error_shapes(profile_schema):
    schema = profile_schema
    operations = schema["paths"]["/api/v1/admin/makerspace/{makerspace_id}/profile"]
    assert {"200", "401", "403", "404"} <= set(operations["get"]["responses"])
    patch = operations["patch"]
    assert {"200", "400", "401", "403", "404", "423", "503"} <= set(patch["responses"])
    assert patch["security"]
    body = resolve(schema, patch["requestBody"]["content"]["application/json"]["schema"])
    assert not body.get("required")
    assert {"timezone", "country", "opening_hours", "default_currency"} <= set(body["properties"])
    error = resolve(schema, patch["responses"]["400"]["content"]["application/json"]["schema"])
    assert set(error["properties"]) == {"code", "detail", "fields"}
    assert error["properties"]["fields"]["additionalProperties"]["type"] == "array"
    gate = resolve(schema, patch["responses"]["423"]["content"]["application/json"]["schema"])
    assert {"code", "detail", "purpose"} == set(gate["properties"])


def test_public_schema_exposes_only_public_profile_fields(profile_schema):
    schema = profile_schema
    operation = schema["paths"]["/api/v1/bootstrap"]["get"]
    response = resolve(schema, operation["responses"]["200"]["content"]["application/json"]["schema"])
    makerspace = resolve(schema, response["properties"]["makerspace"])
    assert {"timezone", "opening_hours"} <= set(makerspace["properties"])
    assert not {"country", "default_currency"} & set(makerspace["properties"])
    hours = makerspace["properties"]["opening_hours"]
    assert "oneOf" in hours
    assert {"weekly", "exceptions"} == set(hours["oneOf"][1]["properties"])
