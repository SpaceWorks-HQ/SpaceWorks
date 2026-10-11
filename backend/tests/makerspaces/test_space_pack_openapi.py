"""Coordinator-run OpenAPI contract and source-catalog coverage."""
from drf_spectacular.generators import SchemaGenerator


def test_pack_routes_have_request_response_and_error_schemas():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    pack_path = next(path for path in schema["paths"] if path.endswith("/space-pack"))
    profile_path = next(path for path in schema["paths"] if path.endswith("/space-pack-profiles"))
    for path, methods in ((pack_path, ("get", "post")), (profile_path, ("get", "post"))):
        for method in methods:
            operation = schema["paths"][path][method]
            assert operation["security"]
            assert {"400", "401", "403", "404"} <= set(operation["responses"])
            assert "requestBody" in operation if method == "post" else True
    assert "409" in schema["paths"][pack_path]["post"]["responses"]
    assert "install_profile_id" in schema["components"]["schemas"]["Makerspace"]["properties"]


def test_profile_model_has_literal_fields_and_no_user_references():
    from apps.makerspaces.models import SpacePackProfile
    from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
    actual = {field.name for field in SpacePackProfile._meta.fields}
    assert actual == FIRST_PARTY_FIELD_NAMES["makerspaces.SpacePackProfile"]
    assert not any(field.is_relation for field in SpacePackProfile._meta.fields)
    from config.admin_scope_registry import GLOBAL_ADMIN_MODELS
    from apps.tenant_migration.gate_policy import HTTP_EXEMPTIONS
    assert "makerspaces.spacepackprofile" in GLOBAL_ADMIN_MODELS
    assert "admin-space-pack-profiles" in HTTP_EXEMPTIONS
