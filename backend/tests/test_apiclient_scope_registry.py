import hashlib
import hmac
import time
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory, override_settings
from django.urls import get_resolver, resolve
from rest_framework.test import APIClient

from apps.apiclients import scope_registry
from apps.apiclients.models import ApiClient
from apps.apiclients.scope_registry import (
    LEGACY_SCOPE,
    SCOPE_REGISTRY,
    TARGET_GLOBAL,
    TARGET_TENANT_SLUG,
    TARGET_TENANT_TOKEN,
    ScopeRegistryEntry,
    lookup,
    resolve_target,
    validate_registry,
)
from apps.hardware_requests.models import HardwareRequest
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db

PUBLIC_PREFIXES = ["/api/public/", "/api/v1/public/"]
PUBLIC_DIRECTORY = "/api/v1/public/makerspaces/"
ORIGIN = "http://localhost:5000"


@pytest.fixture(autouse=True)
def _protected_prefixes(settings):
    settings.HMAC_PROTECTED_PATH_PREFIXES = PUBLIC_PREFIXES
    settings.APICLIENT_REQUIRE_NONCE = False


def _request(path, method="get"):
    request = getattr(RequestFactory(), method)(path)
    request.resolver_match = resolve(request.path_info)
    return request


def _signed_headers(api_client, raw_secret, path=PUBLIC_DIRECTORY):
    timestamp = str(int(time.time()))
    message = b"\n".join([b"GET", path.encode(), timestamp.encode(), b""])
    signature = hmac.new(
        raw_secret.encode(), message, hashlib.sha256
    ).hexdigest()
    return {
        "HTTP_X_CLIENT_ID": api_client.client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_ORIGIN": ORIGIN,
    }


def test_registry_has_no_urlconf_drift():
    stale, missing = validate_registry()

    assert not stale, f"Registry entries reference missing URL names: {stale}"
    assert not missing, f"Protected routes missing registry entries: {missing}"


def test_legacy_cutover_is_explicit_and_new_entries_default_to_excluded():
    assert all(entry.legacy_v1 for entry in SCOPE_REGISTRY.values())
    new_entry = ScopeRegistryEntry(frozenset({"public:read"}), TARGET_GLOBAL)

    assert new_entry.legacy_v1 is False


@pytest.mark.parametrize("prefix", PUBLIC_PREFIXES)
def test_each_protected_prefix_is_covered_independently(prefix):
    route_prefix = prefix.lstrip("/")
    protected = [
        (view_name, method)
        for route, view_name, methods in scope_registry._urlconf_routes(
            get_resolver().url_patterns
        )
        if route.startswith(route_prefix)
        for method in methods
    ]

    assert protected, f"No concrete routes found beneath {prefix}"
    assert not [key for key in protected if key not in SCOPE_REGISTRY]


@pytest.mark.parametrize(
    "path,legacy_name,versioned_name",
    [
        ("makerspaces/", "public-makerspaces", "v1:public-makerspaces"),
        ("alpha/inventory/", "public-inventory", "v1:public-inventory"),
        ("alpha/stats/", "public-makerspace-stats", "v1:public-makerspace-stats"),
        (
            "alpha/inventory/categories/",
            "public-inventory-categories",
            "v1:public-inventory-categories",
        ),
        (
            "alpha/inventory/1/",
            "public-inventory-detail",
            "v1:public-inventory-detail",
        ),
    ],
)
def test_duplicate_inventory_routes_use_distinct_namespaced_keys(
    path, legacy_name, versioned_name
):
    legacy_match = resolve(f"/api/public/{path}")
    versioned_match = resolve(f"/api/v1/public/{path}")

    assert legacy_match.view_name == legacy_name
    assert versioned_match.view_name == versioned_name
    assert legacy_match.view_name != versioned_match.view_name
    assert lookup(legacy_match.view_name, "GET") is not None
    assert lookup(versioned_match.view_name, "GET") is not None


def test_resolve_target_distinguishes_global_valid_and_unknown_slugs():
    makerspace = make_space("scope-registry-slug")
    global_request = _request(PUBLIC_DIRECTORY)
    global_entry = lookup(global_request.resolver_match.view_name, "GET")
    valid_request = _request(f"/api/v1/public/{makerspace.slug}/inventory/")
    slug_entry = lookup(valid_request.resolver_match.view_name, "GET")
    unknown_request = _request("/api/v1/public/not-a-real-space/inventory/")

    assert global_entry.target_mode == TARGET_GLOBAL
    assert resolve_target(global_request, global_entry) == (None, True)
    assert slug_entry.target_mode == TARGET_TENANT_SLUG
    assert resolve_target(valid_request, slug_entry) == (makerspace, True)
    assert resolve_target(unknown_request, slug_entry) == (None, False)


def test_resolve_target_handles_both_opaque_status_tokens(monkeypatch):
    monkeypatch.setattr(
        "apps.encryption.write_fence.assert_mapped_write_allowed", lambda _scope: None
    )
    makerspace = make_space("scope-registry-token")
    requester = make_user("scope-registry-token-user")
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
    )
    printer_type = MachineType.objects.create(
        makerspace=makerspace,
        name="Registry printer",
        slug="3d_printer",
    )
    print_queue = ServiceQueue.objects.create(
        makerspace=makerspace,
        machine_type=printer_type,
        name="Registry queue",
    )
    print_request = MachineServiceRequest.objects.create(
        makerspace=makerspace,
        queue=print_queue,
        requester=requester,
        title="Registry target",
    )
    cases = [
        (
            f"/api/v1/public/requests/{hardware_request.public_token}/status",
            hardware_request.public_token,
        ),
        (
            "/api/v1/public/machine-service/3d-printer/requests/"
            f"{print_request.public_token}/status",
            print_request.public_token,
        ),
    ]

    for path, _token in cases:
        request = _request(path)
        entry = lookup(request.resolver_match.view_name, "GET")
        assert entry.target_mode == TARGET_TENANT_TOKEN
        assert resolve_target(request, entry) == (makerspace, True)

        unknown_path = path.replace(str(_token), str(uuid.uuid4()))
        assert resolve_target(_request(unknown_path), entry) == (None, False)


@override_settings(API_CLIENT_AUTH_REQUIRED=True, CORS_ALLOWED_ORIGINS=[ORIGIN])
def test_empty_scope_issue_is_rejected():
    with pytest.raises(ValidationError, match="At least one API-client scope"):
        ApiClient.issue(
            label="legacy cutover client",
            allowed_origins=[ORIGIN],
            client_type="server",
            scopes=[],
        )


@override_settings(API_CLIENT_AUTH_REQUIRED=True, CORS_ALLOWED_ORIGINS=[ORIGIN])
def test_registry_exception_fails_closed(monkeypatch):
    api_client, raw_secret = ApiClient.issue(
        label="broken registry observer",
        allowed_origins=[ORIGIN],
        client_type="server",
        scopes=[LEGACY_SCOPE],
    )

    def broken_lookup(*_args, **_kwargs):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(scope_registry, "lookup", broken_lookup)

    response = APIClient().get(
        PUBLIC_DIRECTORY,
        **_signed_headers(api_client, raw_secret),
    )

    assert response.status_code == 401


def test_undetectable_methods_on_a_protected_route_count_as_drift(monkeypatch):
    """A protected route whose methods cannot be derived must FAIL the guard.

    `_concrete_methods` reads the handler names off a class-based view. A future
    function-based public route would yield an empty method set, contribute nothing
    to `missing`, and so sail through the completeness guard while being entirely
    unregistered -- the one failure mode this guard exists to prevent.
    """
    real = scope_registry._urlconf_routes

    def with_a_methodless_protected_route(*args, **kwargs):
        yield from real(*args, **kwargs)
        yield "api/public/mystery/", "public-mystery-function-view", set()

    monkeypatch.setattr(
        scope_registry, "_urlconf_routes", with_a_methodless_protected_route
    )

    stale, missing = scope_registry.validate_registry()

    assert stale == []
    assert ("public-mystery-function-view", "") in missing


def test_a_dropped_method_leaves_a_stale_registry_entry(monkeypatch):
    """Stale must be measured per (view_name, method), not per view name.

    A handler that drops a method -- or a route that moves out from behind a
    protected prefix while keeping its name -- would otherwise leave a live
    authorization key in the registry that no route can ever match again, and the
    drift test would still pass.
    """
    real = scope_registry._urlconf_routes

    def without_the_directory_post(*args, **kwargs):
        for route, view_name, methods in real(*args, **kwargs):
            if view_name == "v1:public-makerspaces":
                yield route, view_name, set()
                continue
            yield route, view_name, methods

    monkeypatch.setattr(scope_registry, "_urlconf_routes", without_the_directory_post)

    stale, _missing = scope_registry.validate_registry()

    assert ("v1:public-makerspaces", "GET") in stale
    assert ("v1:public-makerspaces", "HEAD") in stale


def test_a_route_leaving_the_protected_prefix_is_stale(monkeypatch):
    real = scope_registry._urlconf_routes

    def moved_out_of_the_public_prefix(*args, **kwargs):
        for route, view_name, methods in real(*args, **kwargs):
            if view_name == "v1:public-makerspaces":
                yield "api/v1/internal/makerspaces/", view_name, methods
                continue
            yield route, view_name, methods

    monkeypatch.setattr(scope_registry, "_urlconf_routes", moved_out_of_the_public_prefix)

    stale, _missing = scope_registry.validate_registry()

    assert ("v1:public-makerspaces", "GET") in stale
