"""Creation and organization reach expose authenticated, complete OpenAPI contracts."""
from django.urls import path
from drf_spectacular.generators import SchemaGenerator

from apps.admin_api.views_makerspaces import MakerspaceListCreateView
from apps.organizations.views_admin import OrganizationListView
from apps.organizations.views_console import OrganizationLinksView, OrganizationLinkDeleteView


def resolve(schema, node):
    if "$ref" in node:
        return resolve(schema, schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]])
    # drf-spectacular wraps optional nested components in allOf to attach field
    # metadata without changing the referenced component's object schema.
    if "allOf" in node:
        resolved = {key: value for key, value in node.items() if key != "allOf"}
        for component in node["allOf"]:
            resolved.update(resolve(schema, component))
        return resolved
    return node


def schema():
    return SchemaGenerator(patterns=[
        path("api/v1/admin/makerspaces", MakerspaceListCreateView.as_view()),
        path("api/v1/admin/organizations/", OrganizationListView.as_view()),
        path("api/v1/admin/organizations/<int:pk>/makerspaces/", OrganizationLinksView.as_view()),
        path("api/v1/admin/organizations/<int:pk>/makerspaces/<int:makerspace_id>/", OrganizationLinkDeleteView.as_view()),
    ]).get_schema(request=None, public=True)


def test_nested_creation_setup_is_documented_as_input_and_delivery_as_output():
    document = schema()
    operation = document["paths"]["/api/v1/admin/makerspaces"]["post"]
    body = resolve(document, operation["requestBody"]["content"]["application/json"]["schema"])
    setup = resolve(document, body["properties"]["creation_setup"])
    assert {"profile", "modules", "first_staff_invite"} <= set(setup["properties"])
    profile = resolve(document, setup["properties"]["profile"])
    assert not [name for name in profile.get("required", [])
                if not profile["properties"][name].get("readOnly")]
    assert {"timezone", "country", "opening_hours", "default_currency"} <= set(profile["properties"])
    output = resolve(document, operation["responses"]["201"]["content"]["application/json"]["schema"])
    assert "creation_invitation" in output["properties"]
    assert operation["security"]
    assert {"400", "401", "403", "404", "409", "423", "503"} <= set(operation["responses"])


def test_organization_reach_routes_document_auth_requests_results_and_error_bodies():
    document = schema()
    for route, operations in document["paths"].items():
        if "/organizations/" not in route:
            continue
        for method, operation in operations.items():
            if method not in {"post", "get", "delete"} or (method == "get" and route.endswith("/organizations/")):
                continue
            assert operation["security"]
            assert {"401", "403"} <= set(operation["responses"])
            if method == "post":
                assert operation["requestBody"]["content"]["application/json"]["schema"]
                assert "400" in operation["responses"] and "409" in operation["responses"]
            else:
                assert "requestBody" not in operation
            for code, response in operation["responses"].items():
                if int(code) >= 400:
                    assert response["content"]["application/json"]["schema"]["type"] == "object"
            if method == "delete":
                assert "204" in operation["responses"]
