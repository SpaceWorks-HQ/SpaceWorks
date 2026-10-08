"""Every cloud-surface route documents the errors it really answers (cloud lane).

The repo rule is that an undocumented error response makes an endpoint incomplete. At
`b7c2ee93` 151 of 612 operations documented no 4xx/5xx at all, including every platform
settings route, the health probes and the Telegram webhook. This pins the in-scope ones by
the exact codes their views return, so a regression in either direction shows up here.
"""

import pytest
from drf_spectacular.generators import SchemaGenerator

pytestmark = pytest.mark.django_db

M = "/api/v1/admin/makerspace/{makerspace_id}"

EXPECTED = {
    ("/api/v1/health/", "get"): {"503"},
    ("/api/v1/health/readiness/", "get"): {"503"},
    ("/api/v1/live/", "get"): {"401", "503"},
    ("/api/v1/metrics/", "get"): {"401", "404"},
    ("/api/v1/internal/tls-check", "get"): {"400", "403", "503"},
    ("/api/v1/integrations/telegram/webhook", "post"): {"400", "403", "429"},
    ("/api/v1/integrations/telegram/test-alert", "post"): {"400", "401", "403", "404"},
    ("/api/v1/admin/platform/email-settings", "get"): {"401", "403"},
    ("/api/v1/admin/platform/email-settings", "patch"): {"400", "401", "403"},
    ("/api/v1/admin/platform/social-auth-settings", "get"): {"401", "403"},
    ("/api/v1/admin/platform/social-auth-settings", "patch"): {"400", "401", "403"},
    ("/api/v1/admin/platform/payment-settings", "get"): {"401", "403", "404"},
    ("/api/v1/admin/platform/payment-settings", "patch"): {"400", "401", "403", "404"},
    ("/api/v1/admin/platform/update-settings", "get"): {"401", "403", "404"},
    ("/api/v1/admin/platform/update-settings", "patch"): {"400", "401", "403", "404"},
    ("/api/v1/admin/platform/update-settings/update-now", "post"): {"401", "403", "404"},
    ("/api/v1/admin/api-key-requests", "get"): {"400", "401", "403"},
    ("/api/v1/admin/api-key-requests", "post"): {"400", "401", "403"},
    (f"{M}/api-settings", "get"): {"401", "403", "404"},
    (f"{M}/api-settings", "patch"): {"400", "401", "403", "404"},
    (f"{M}/notification-destinations", "get"): {"401", "403", "404"},
    (f"{M}/notification-destinations/{{destination_id}}", "delete"): {"401", "403", "404"},
    (f"{M}/notification-recipient-rules", "get"): {"401", "403", "404"},
    (f"{M}/notification-recipients", "get"): {"401", "403", "404"},
    (f"{M}/notification-recipients", "patch"): {"400", "401", "403", "404"},
    (f"{M}/notification-rules", "get"): {"401", "403", "404"},
    (f"{M}/email-templates", "get"): {"401", "403", "404"},
    (f"{M}/email-templates/preview", "post"): {"400", "401", "403", "404"},
    (f"{M}/email-templates/{{stream}}/{{audience}}/{{key}}", "get"): {"401", "403", "404"},
    (f"{M}/email-templates/{{stream}}/{{audience}}/{{key}}", "patch"): {"400", "401", "403", "404"},
    (f"{M}/email-templates/{{stream}}/{{audience}}/{{key}}/reset", "post"): {"401", "403", "404"},
    (f"{M}/modules", "get"): {"401", "403", "404"},
}


@pytest.fixture(scope="module")
def paths(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        return SchemaGenerator().get_schema(request=None, public=True)["paths"]


@pytest.mark.parametrize("key", sorted(EXPECTED), ids=lambda k: f"{k[1].upper()} {k[0]}")
def test_cloud_route_documents_its_error_responses(paths, key):
    path, method = key
    responses = paths[path][method]["responses"]

    missing = EXPECTED[key] - set(responses)
    assert not missing, f"{method.upper()} {path} does not document {sorted(missing)}"
    for code in EXPECTED[key]:
        assert responses[code].get("description"), f"{code} on {path} has no description"


def test_list_routes_kept_their_paginated_success_schema(paths):
    """Adding error responses must not drop DRF pagination from a list's 200."""
    ok = paths["/api/v1/admin/api-key-requests"]["get"]["responses"]["200"]
    ref = ok["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/PaginatedApiKeyRequestList")
