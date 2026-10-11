"""The new surfaces participate in the real route and source-gate inventories."""

import pytest
from drf_spectacular.generators import SchemaGenerator

pytestmark = pytest.mark.django_db


def test_new_claim_routes_and_policy_hooks_pass_the_complete_guard():
    from apps.accounts.claim_route_guard import validate_claim_route_matrix
    validate_claim_route_matrix()


def test_bounce_ingress_is_a_declared_anonymous_tenant_writer():
    from apps.tenant_migration.source_gate_guards import validate_source_gate_coverage
    validate_source_gate_coverage()


def test_wp3_openapi_declares_requests_responses_and_errors():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    operations = {
        '/api/v1/integrations/makerspace/{makerspace_id}/bounce-webhook': ('post',),
        '/api/v1/integrations/makerspace/{makerspace_id}/timing-policy': ('get', 'patch'),
        '/api/v1/notifications/broadcasts/{makerspace_id}': ('get', 'post'),
        '/api/v1/notifications/announcements/{makerspace_id}': ('get',),
        '/api/v1/admin/spaces/{id}/recurring-bookings/': ('post',),
        '/api/v1/public/{makerspace_slug}/my-bookings/{public_token}/reschedule/': ('post',),
        '/api/v1/public/{makerspace_slug}/my-bookings/calendar/': ('get', 'post', 'delete'),
    }
    for path, methods in operations.items():
        for method in methods:
            operation = schema['paths'][path][method]
            assert {'400', '403', '404'} <= operation['responses'].keys(), (path, method)
            if method in {'post', 'patch'} and 'calendar/' not in path:
                assert 'requestBody' in operation, (path, method)
            assert any(code.startswith('2') for code in operation['responses'])
