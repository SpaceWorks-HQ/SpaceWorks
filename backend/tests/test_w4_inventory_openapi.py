from drf_spectacular.generators import SchemaGenerator


def _resolve(schema, node):
    if "$ref" in node:
        return schema["components"]["schemas"][node["$ref"].split("/")[-1]]
    return node


def test_inventory_routes_document_requests_responses_auth_and_errors():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = schema["paths"]
    base = "/api/v1/admin/makerspace/{makerspace_id}"
    for path, method, successes in (
        (f"{base}/kit-checklist-preview", "post", {"200"}),
        (f"{base}/inventory/reorder-suggestions", "get", {"200"}),
        (f"{base}/inventory/reorder-draft", "post", {"200", "201"}),
        (f"{base}/inventory", "post", {"201"}),
        ("/api/v1/public/{makerspace_slug}/tools/checklist", "post", {"200"}),
    ):
        operation = paths[path][method]
        assert successes | {"400", "401", "403", "404"} <= set(operation["responses"])
        assert operation["security"]
        if method == "post":
            assert operation["requestBody"]["content"]["application/json"]["schema"]

    product = _resolve(schema, paths[f"{base}/inventory"]["post"]["requestBody"]
                       ["content"]["application/json"]["schema"])
    components = product["properties"]["kit_components"]
    assert components["type"] == "array"
    component = _resolve(schema, components["items"])
    assert {"key", "label", "quantity"} <= set(component["properties"])
    assert component["properties"]["key"]["format"] == "uuid"
    issue = paths["/api/v1/admin/requests/{id}/issue"]["post"]
    assert {"200", "400", "401", "403", "404", "409", "503"} <= set(issue["responses"])
    body = _resolve(schema, issue["requestBody"]["content"]["application/json"]["schema"])
    count = _resolve(schema, body["properties"]["kit_checklist"]["items"])
    assert {"key", "present"} <= set(count["properties"])
