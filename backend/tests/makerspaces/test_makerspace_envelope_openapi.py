"""The makerspace-envelope routes document their error responses.

`CLAUDE.md` requires every route to carry its request, response and error schemas; the
2026-10-09 audit found the core settings routes documenting only their 200. This pins
the documented status codes so a later edit cannot quietly drop them (the
`tests/bookings/test_admin_api.py` precedent).
"""

import pytest
from drf_spectacular.generators import SchemaGenerator

EXPECTED = {
    "/api/v1/admin/makerspaces": {"get": {"200", "403"}, "post": {"201", "400", "403"}},
    "/api/v1/admin/makerspaces/{id}": {
        "get": {"200", "404"},
        "patch": {"200", "400", "403", "404"},
    },
    "/api/v1/admin/makerspace/{makerspace_id}/return-policy": {
        "get": {"200", "404"},
        "patch": {"200", "400", "404"},
    },
    "/api/v1/admin/makerspace/{makerspace_id}/api-settings": {
        "get": {"200", "403", "404"},
        "patch": {"200", "400", "403", "404"},
    },
    "/api/v1/admin/makerspace/{makerspace_id}/logo": {
        "post": {"201", "400", "403", "404", "503"},
        "put": {"200", "400", "403", "404", "503"},
        "delete": {"200", "403", "404"},
    },
    "/api/v1/admin/makerspace/{makerspace_id}/cover": {
        "post": {"201", "400", "403", "404", "503"},
        "put": {"200", "400", "403", "404", "503"},
        "delete": {"200", "403", "404"},
    },
    "/api/v1/admin/makerspace/{makerspace_id}/modules": {"get": {"200", "403", "404"}},
    "/api/v1/admin/makerspace/{makerspace_id}/modules/install": {
        "post": {"200", "400", "403", "404"},
    },
    "/api/v1/admin/makerspace/{makerspace_id}/modules/uninstall": {
        "post": {"200", "400", "403", "404"},
    },
    "/api/v1/admin/memberships/{id}": {"delete": {"204", "403", "404"}},
}


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_envelope_route_documents_its_error_responses(schema, path):
    operations = schema["paths"][path]
    for method, codes in EXPECTED[path].items():
        documented = set(operations[method]["responses"])
        assert codes <= documented, (path, method, sorted(codes - documented))
