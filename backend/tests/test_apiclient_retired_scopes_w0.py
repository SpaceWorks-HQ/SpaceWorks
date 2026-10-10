from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from django.core.exceptions import ValidationError

from apps.apiclients import checks, scope_registry
from apps.apiclients.scope_grants import scope_catalog, validate_grantable_scopes
from apps.apiclients.models import ApiClient
from apps.apiclients.scope_registry import (
    LEGACY_SCOPE, SCOPE_REGISTRY, SCOPE_VOCABULARY, ScopeRegistryEntry, TARGET_GLOBAL,
)

RETIRED = ("admin:read", "admin:write", "admin:*", "reports:read")


@pytest.mark.parametrize("scope", RETIRED)
@pytest.mark.parametrize("privileged", [False, True])
def test_retired_scopes_cannot_be_granted_or_advertised(scope, privileged):
    with pytest.raises(ValueError, match="Unknown API-client scope"):
        validate_grantable_scopes([scope], privileged=privileged)
    assert scope not in {option["value"] for option in scope_catalog(privileged=privileged)}


@pytest.mark.parametrize("scope", RETIRED)
def test_historical_retired_grants_do_not_authorize_any_registered_route(scope):
    assert all(not scope_registry.scope_allows(entry, [scope]) for entry in SCOPE_REGISTRY.values())
    request = RequestFactory().get("/api/v1/admin/reports")
    request.resolver_match = SimpleNamespace(view_name="unregistered-admin", kwargs={})
    client = SimpleNamespace(scopes=[scope], makerspace_id=None)
    assert not scope_registry.classify(request, client).verdict


@pytest.mark.parametrize("scope", RETIRED)
def test_direct_issuance_rejects_retired_scopes_before_creating_a_client(scope):
    with pytest.raises(ValidationError, match="Unknown API-client scope"):
        ApiClient.issue(label="Retired", scopes=[scope], allowed_origins=["https://client.example"])


def test_supported_scope_catalog_exactly_covers_route_scopes_and_legacy():
    used = {scope for entry in SCOPE_REGISTRY.values() for scope in entry.scopes}
    assert SCOPE_VOCABULARY == used | {LEGACY_SCOPE}
    assert checks.check_scope_registry(app_configs=None, databases=None) == []


@pytest.mark.parametrize("drift", ["unused", "unknown"])
def test_system_check_rejects_scope_catalog_drift(monkeypatch, drift):
    if drift == "unused":
        monkeypatch.setattr(checks, "SCOPE_VOCABULARY", SCOPE_VOCABULARY | {"reports:read"})
    else:
        registry = dict(SCOPE_REGISTRY)
        registry[("unregistered-admin", "GET")] = ScopeRegistryEntry(
            frozenset({"admin:read"}), TARGET_GLOBAL
        )
        monkeypatch.setattr(checks, "SCOPE_REGISTRY", registry)
    errors = checks.check_scope_registry(app_configs=None, databases=None)
    assert [error.id for error in errors] == ["apiclients.E002"]
