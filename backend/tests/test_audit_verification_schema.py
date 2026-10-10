"""The async staff routes document their actual paginated and aggregate contracts."""

from drf_spectacular.generators import SchemaGenerator


def test_verification_routes_have_request_response_and_error_schemas():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    base = "/api/v1/admin/makerspace/{makerspace_id}/audit-verifications"
    listing = schema["paths"][base]
    detail = schema["paths"][base + "/{run_id}"]["get"]
    for operation in (listing["get"], listing["post"], detail):
        assert {"400", "401", "403", "404"} <= operation["responses"].keys()
        assert operation["security"]
        for status in ("400", "401", "403", "404"):
            assert "schema" in operation["responses"][status]["content"]["application/json"]
    assert {"202", "409", "429"} <= listing["post"]["responses"].keys()
    assert "application/json" in listing["post"]["requestBody"]["content"]
    assert "application/json" in listing["post"]["responses"]["429"]["content"]
    assert any(param["name"] == "page" for param in listing["get"]["parameters"])
    response = listing["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    page = schema["components"]["schemas"][response["$ref"].rsplit("/", 1)[-1]]
    assert set(page["properties"]) == {"count", "next", "previous", "results"}
    assert page["properties"]["results"]["type"] == "array"
