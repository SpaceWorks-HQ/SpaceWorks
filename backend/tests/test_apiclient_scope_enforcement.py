import hashlib
import hmac
import time
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, override_settings
from django.urls import resolve
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.admin_api.api_client_serializers import ApiClientSerializer
from apps.apiclients import scope_registry
from apps.apiclients.checks import check_scope_registry
from apps.apiclients.models import ApiClient as ApiClientModel
from apps.apiclients.scope_registry import (
    ADMIN_ALL,
    LEGACY_SCOPE,
    PUBLIC_ALL,
    PUBLIC_READ,
    SCOPE_REGISTRY,
    TARGET_GLOBAL,
    ScopeRegistryEntry,
)
from apps.inventory.middleware import FrontendHMACMiddleware
from tests.return_helpers import authenticated_client, make_member, make_space


ORIGIN = "https://scope-client.example.test"
PUBLIC_PREFIXES = ["/api/public/", "/api/v1/public/"]


def _middleware():
    return FrontendHMACMiddleware(lambda request: request)


def _request(path, method="get"):
    request = getattr(RequestFactory(), method)(path)
    try:
        request.resolver_match = resolve(request.path_info)
    except Exception:
        pass
    return request


def _principal(scopes, makerspace_id=None):
    return SimpleNamespace(scopes=scopes, makerspace_id=makerspace_id)


def _signed_headers(client_id, secret, path):
    timestamp = str(int(time.time()))
    message = b"\n".join([b"GET", path.encode(), timestamp.encode(), b""])
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_CLIENT_ID": client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_ORIGIN": ORIGIN,
    }


@pytest.mark.parametrize("scope", [LEGACY_SCOPE, PUBLIC_ALL, ADMIN_ALL])
def test_unknown_protected_route_denies_before_wildcards(scope):
    request = _request("/api/v1/public/unregistered/")

    assert _middleware()._request_scope_ok(request, _principal([scope])) is False


def test_legacy_scope_is_limited_to_entries_frozen_into_v1(monkeypatch):
    target = SimpleNamespace(pk=1)
    monkeypatch.setattr(scope_registry, "resolve_target", lambda *_args: (target, True))
    client = _principal([LEGACY_SCOPE])

    for (view_name, method), entry in SCOPE_REGISTRY.items():
        request = getattr(RequestFactory(), method.lower())("/registered/")
        request.resolver_match = SimpleNamespace(view_name=view_name, kwargs={})
        assert entry.legacy_v1 is True
        assert scope_registry.classify(request, client).verdict is True

    excluded = ScopeRegistryEntry(frozenset({PUBLIC_READ}), TARGET_GLOBAL)
    monkeypatch.setattr(scope_registry, "lookup", lambda *_args: excluded)
    request = _request("/api/v1/public/makerspaces/")
    assert scope_registry.classify(request, client).verdict is False


@pytest.mark.django_db
def test_tenant_mismatch_unresolved_target_and_global_client_rules():
    own_space = make_space("scope-enforcement-own")
    other_space = make_space("scope-enforcement-other")
    middleware = _middleware()
    mismatched = _request(f"/api/v1/public/{own_space.slug}/inventory/")
    unresolved = _request("/api/v1/public/no-such-makerspace/inventory/")
    directory = _request("/api/v1/public/makerspaces/")

    assert middleware._request_scope_ok(
        mismatched, _principal([PUBLIC_READ], other_space.pk)
    ) is False
    assert middleware._request_scope_ok(
        unresolved, _principal([PUBLIC_READ], own_space.pk)
    ) is False
    assert middleware._request_scope_ok(
        directory, _principal([PUBLIC_READ])
    ) is True
    assert middleware._request_scope_ok(
        directory, _principal([LEGACY_SCOPE], own_space.pk)
    ) is True


@pytest.mark.django_db
@override_settings(
    API_CLIENT_AUTH_REQUIRED=True,
    APICLIENT_REQUIRE_NONCE=False,
    CORS_ALLOWED_ORIGINS=[ORIGIN],
    HMAC_PROTECTED_PATH_PREFIXES=PUBLIC_PREFIXES,
)
def test_tenant_serializer_default_client_reaches_public_route():
    makerspace = make_space("scope-enforcement-tenant")
    manager = make_member("scope-enforcement-manager", makerspace)
    created = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.pk}/api-clients",
        {"label": "Tenant web", "allowed_origins": [ORIGIN], "scopes": ["public:read"]},
        format="json",
    )
    path = f"/api/v1/public/{makerspace.slug}/inventory/"

    assert created.status_code == 201
    stored = ApiClientModel.objects.get(pk=created.data["id"])
    assert stored.scopes == ["public:read"]
    response = APIClient().get(
        path,
        **_signed_headers(stored.client_id, created.data["client_secret"], path),
    )
    assert response.status_code == 200


def test_scope_registry_system_check_catches_widened_prefix():
    with override_settings(HMAC_PROTECTED_PATH_PREFIXES=PUBLIC_PREFIXES):
        assert check_scope_registry(None) == []

    with override_settings(HMAC_PROTECTED_PATH_PREFIXES=["/api/v1/admin/"]):
        errors = check_scope_registry(None)

    assert len(errors) == 1
    assert errors[0].id == "apiclients.E001"
    assert "/api/v1/admin/" in errors[0].msg


@pytest.mark.parametrize(
    "scopes,expected_message",
    [
        (["not:a:scope"], "Unknown API-client scope"),
        (["admin:write"], "Browser clients may only use public/read scopes"),
    ],
)
def test_serializer_rejects_unknown_and_browser_write_scopes(scopes, expected_message):
    request = RequestFactory().post("/api/v1/admin/makerspace/1/api-clients")
    request.user = SimpleNamespace(is_superuser=True, role=User.Role.SUPERADMIN)
    serializer = ApiClientSerializer(
        data={
            "label": "Invalid scopes",
            "client_type": "browser",
            "scopes": scopes,
            "allowed_origins": [ORIGIN],
        },
        context={"request": request},
    )

    assert serializer.is_valid() is False
    assert expected_message in str(serializer.errors["scopes"])


@pytest.mark.django_db(transaction=True)
def test_legacy_scope_data_migration_is_reversible():
    from_target = [("apiclients", "0003_apikeyrequest")]
    target = [("apiclients", "0004_legacy_v1_scopes")]
    executor = MigrationExecutor(connection)

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        OldApiClient = old_apps.get_model("apiclients", "ApiClient")
        client = OldApiClient.objects.create(
            label="Pre-cutover client",
            client_id="ck_pre_cutover",
            secret_encrypted=b"encrypted-placeholder",
            scopes=[],
        )

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        NewApiClient = new_apps.get_model("apiclients", "ApiClient")
        assert NewApiClient.objects.get(pk=client.pk).scopes == [LEGACY_SCOPE]

        executor = MigrationExecutor(connection)
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        assert old_apps.get_model("apiclients", "ApiClient").objects.get(
            pk=client.pk
        ).scopes == []
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())


def test_the_registry_system_check_runs_the_way_django_calls_it():
    """Django calls checks as check(app_configs=..., databases=...), by KEYWORD.

    A positional-only or misnamed parameter makes `manage.py check` -- and therefore
    migrate, runserver and container boot -- raise TypeError before startup. pytest does
    not run system checks, so only calling it Django's way catches that.
    """
    from django.core.checks import registry as checks_registry

    from apps.apiclients.checks import check_scope_registry

    assert check_scope_registry(app_configs=None, databases=None) == []

    registered = [
        check
        for check in checks_registry.registry.get_checks(include_deployment_checks=False)
        if check is check_scope_registry
    ]
    assert registered, "the scope registry check is not registered"
    for check in registered:
        assert check(app_configs=None, databases=None) == []


@pytest.mark.django_db
def test_every_creation_path_gets_the_legacy_capability_not_an_empty_list():
    """issue() is not the only way a client is created.

    The /control/ ModelAdmin and seed_demo build rows directly. With the registry
    authoritative, an empty scopes list is DENIED, so such a client would 401 on every
    protected route -- and the admin exposes no scopes field to repair it.
    """
    direct = ApiClientModel(label="built directly", allowed_origins=[ORIGIN])
    direct.set_secret("secret-value")
    direct.save()

    direct.refresh_from_db()
    assert direct.scopes == [scope_registry.LEGACY_SCOPE]

    explicit = ApiClientModel(
        label="explicit scopes", allowed_origins=[ORIGIN], scopes=["public:read"]
    )
    explicit.set_secret("secret-value")
    explicit.save()
    explicit.refresh_from_db()
    assert explicit.scopes == ["public:read"]
