"""Every owned-account route documents its actual request and error shapes."""
import pytest
from django.urls import include, path
from drf_spectacular.generators import SchemaGenerator

from apps.makerspaces.urls import urlpatterns


@pytest.fixture(scope="module")
def account_schema():
    routes = [route for route in urlpatterns if route.name and (
        route.name.startswith("member-account-") or route.name.startswith("member-subject-export-")
    )]
    return SchemaGenerator(patterns=[path("api/v1/", include(routes))]).get_schema(request=None, public=True)


def test_all_account_routes_document_auth_and_typed_errors(account_schema):
    assert len(account_schema["paths"]) == 9
    for operations in account_schema["paths"].values():
        for method, operation in operations.items():
            if method not in {"get", "post", "patch", "delete"}:
                continue
            assert operation["security"]
            assert {"400", "401", "403", "404", "423", "429", "503"} <= set(operation["responses"])
            invalid = operation["responses"]["400"]["content"]["application/json"]["schema"]
            assert invalid["additionalProperties"]["oneOf"][1]["type"] == "array"
            assert "schema" in operation["responses"]["401"]["content"]["application/json"]


def test_export_request_documents_an_empty_object(account_schema):
    base = "/api/v1/member/makerspaces/{makerspace_id}/account"
    create = account_schema["paths"][base + "/exports"]["post"]
    body = create["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"type": "object", "additionalProperties": False}
    assert "202" in create["responses"]
    for suffix in ("cancel", "leave"):
        operation = account_schema["paths"][base + "/" + suffix]["post"]
        node = operation["requestBody"]["content"]["application/json"]["schema"]
        definition = account_schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]
        assert "reason" in definition["required"]
