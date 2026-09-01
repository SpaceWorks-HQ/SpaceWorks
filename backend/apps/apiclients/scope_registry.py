from dataclasses import dataclass

from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver, resolve

from apps.apiclients.scope_registry_routes import (
    ADMIN_ALL,
    ADMIN_READ,
    ADMIN_WRITE,
    PUBLIC_ALL,
    PUBLIC_READ,
    PUBLIC_WRITE,
    REPORTS_READ,
    SCOPE_REGISTRY,
    TARGET_GLOBAL,
    TARGET_MODES,
    TARGET_TENANT_SLUG,
    TARGET_TENANT_TOKEN,
    ScopeRegistryEntry,
)

LEGACY_SCOPE = "legacy:v1"
SCOPE_VOCABULARY = frozenset(
    {
        LEGACY_SCOPE,
        PUBLIC_READ,
        PUBLIC_WRITE,
        PUBLIC_ALL,
        ADMIN_READ,
        ADMIN_WRITE,
        ADMIN_ALL,
        REPORTS_READ,
    }
)
BROWSER_SCOPES = frozenset(
    {
        LEGACY_SCOPE,
        PUBLIC_READ,
        PUBLIC_WRITE,
        PUBLIC_ALL,
        ADMIN_READ,
        REPORTS_READ,
    }
)


@dataclass(frozen=True, slots=True)
class ScopeObservation:
    view_name: str | None
    method: str
    verdict: bool
    target_resolution: str
    target_resolved: bool | None
    target_makerspace_id: int | None


def lookup(view_name, method):
    if not view_name or not method:
        return None
    return SCOPE_REGISTRY.get((view_name, method.upper()))


def _request_match(request):
    match = getattr(request, "resolver_match", None)
    if match is not None:
        return match
    if hasattr(request, "_scope_registry_resolver_match"):
        return request._scope_registry_resolver_match
    try:
        match = resolve(request.path_info)
    except Exception:
        match = None
    request._scope_registry_resolver_match = match
    return match


def resolve_view_name(request):
    try:
        match = _request_match(request)
        return getattr(match, "view_name", None) if match is not None else None
    except Exception:
        return None


def resolve_target(request, entry):
    if entry.target_mode == TARGET_GLOBAL:
        return None, True
    try:
        match = _request_match(request)
        kwargs = getattr(match, "kwargs", {}) or {}
        if entry.target_mode == TARGET_TENANT_SLUG:
            from apps.makerspaces.lookup import get_public_makerspace

            # get_public_makerspace raises Http404 for an unknown or unservable
            # identifier, which the outer except turns into resolved=False. The
            # explicit None check keeps that contract if it ever starts returning
            # None instead: an unresolved tenant must never read as resolved, or
            # the fail-open this registry exists to close comes straight back.
            target = get_public_makerspace(kwargs.get("makerspace_slug"))
            return (target, True) if target is not None else (None, False)
        if entry.target_mode != TARGET_TENANT_TOKEN:
            return None, False
        token = kwargs.get("public_token")
        view_name = getattr(match, "view_name", None)
        if view_name == "hardware_requests:request-status":
            from apps.hardware_requests.models import HardwareRequest

            row = HardwareRequest.objects.select_related("makerspace").filter(
                public_token=token
            ).first()
        elif view_name == "public-printer-service-status":
            from apps.machines.models import MachineServiceRequest

            row = MachineServiceRequest.objects.select_related("makerspace").filter(
                public_token=token
            ).first()
        else:
            return None, False
        return (row.makerspace, True) if row is not None else (None, False)
    except Exception:
        return None, False


def resolve_target_once(request, entry):
    if hasattr(request, "_api_client_scope_target"):
        return request._api_client_scope_target
    result = resolve_target(request, entry)
    request._api_client_scope_target = result
    return result


def target_allows(entry, client, target, resolved):
    if entry.target_mode == TARGET_GLOBAL:
        return client.makerspace_id is None or entry.tenant_apps_admitted
    if not resolved:
        return False
    target_id = getattr(target, "pk", None)
    return client.makerspace_id is None or target_id == client.makerspace_id


def scope_allows(entry, scopes):
    scopes = frozenset(scopes or ())
    if LEGACY_SCOPE in scopes and entry.legacy_v1:
        return True
    return not scopes.isdisjoint(entry.scopes)


def classify(request, client):
    view_name = resolve_view_name(request)
    method = request.method.upper()
    entry = lookup(view_name, method)
    if entry is None:
        return ScopeObservation(view_name, method, False, "no_registry_entry", None, None)

    target, resolved = resolve_target_once(request, entry)
    target_id = getattr(target, "pk", None)
    target_resolution = "global" if entry.target_mode == TARGET_GLOBAL else "resolved"
    if not resolved:
        return ScopeObservation(view_name, method, False, "unresolved", False, None)
    if not target_allows(entry, client, target, resolved):
        return ScopeObservation(
            view_name, method, False, target_resolution, True, target_id
        )
    verdict = scope_allows(entry, client.scopes)
    return ScopeObservation(
        view_name, method, verdict, target_resolution, True, target_id
    )


def _concrete_methods(callback):
    view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
    if view_class is None:
        return set()
    methods = {
        method.upper()
        for method in ("get", "post", "put", "patch", "delete")
        if callable(getattr(view_class, method, None))
    }
    if "GET" in methods:
        methods.add("HEAD")
    return methods


def _urlconf_routes(patterns, route="", namespaces=()):
    for pattern in patterns:
        full_route = route + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            child_namespaces = namespaces + ((pattern.namespace,) if pattern.namespace else ())
            yield from _urlconf_routes(pattern.url_patterns, full_route, child_namespaces)
            continue
        if not isinstance(pattern, URLPattern):
            continue
        view_name = ":".join((*namespaces, pattern.name)) if pattern.name else None
        yield full_route, view_name, _concrete_methods(pattern.callback)


def validate_registry():
    routes = list(_urlconf_routes(get_resolver().url_patterns))
    prefixes = tuple(prefix.lstrip("/") for prefix in settings.HMAC_PROTECTED_PATH_PREFIXES)
    protected = [
        (route, view_name, methods)
        for route, view_name, methods in routes
        if route.startswith(prefixes)
    ]
    # Stale is measured against the concrete protected (view_name, method) keys, not
    # against view names anywhere in the URLconf. Comparing names alone would keep an
    # obsolete authorization key whenever a handler drops a method, or when a route
    # moves out from behind a protected prefix while keeping its name.
    protected_keys = {
        (view_name, method)
        for _route, view_name, methods in protected
        for method in methods
    }
    stale = sorted(key for key in SCOPE_REGISTRY if key not in protected_keys)
    # A protected route whose methods cannot be derived contributes nothing to
    # `missing`, so it would pass the completeness guard while being unregistered.
    # Report it as its own drift class: today every protected route is a class-based
    # view, and a future function-based one must fail this test rather than slip
    # through it. `(view_name, "")` marks the method set as undetermined.
    missing = sorted([
        (view_name, method)
        for _route, view_name, methods in protected
        for method in (methods or {""})
        if (view_name, method) not in SCOPE_REGISTRY
    ], key=lambda item: (item[0] or "", item[1]))
    return stale, missing


def unregistered_protected_routes():
    prefixes = tuple(prefix.lstrip("/") for prefix in settings.HMAC_PROTECTED_PATH_PREFIXES)
    missing = [
        (route, view_name, method)
        for route, view_name, methods in _urlconf_routes(get_resolver().url_patterns)
        if route.startswith(prefixes)
        for method in (methods or {""})
        if (view_name, method) not in SCOPE_REGISTRY
    ]
    return sorted(missing, key=lambda item: (item[0], item[1] or "", item[2]))


__all__ = [
    "ADMIN_ALL", "ADMIN_READ", "ADMIN_WRITE", "BROWSER_SCOPES", "LEGACY_SCOPE",
    "PUBLIC_ALL", "PUBLIC_READ", "PUBLIC_WRITE", "REPORTS_READ", "SCOPE_REGISTRY",
    "SCOPE_VOCABULARY", "TARGET_GLOBAL", "TARGET_MODES", "TARGET_TENANT_SLUG",
    "TARGET_TENANT_TOKEN", "ScopeObservation", "ScopeRegistryEntry", "classify",
    "lookup", "resolve_target", "resolve_target_once", "resolve_view_name",
    "scope_allows", "target_allows", "unregistered_protected_routes",
    "validate_registry",
]
