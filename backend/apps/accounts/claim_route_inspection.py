"""Structural URL and handler inspection for the claim-route drift guard."""

from dataclasses import dataclass
from functools import lru_cache
import inspect

from django.urls import URLPattern, URLResolver
from django.urls.resolvers import RegexPattern
from rest_framework.viewsets import ViewSet, ViewSetMixin
from rest_framework.views import APIView

from apps.accounts.claim_routes import CLAIM_REACHABLE_PREFIXES


@dataclass(frozen=True, slots=True)
class ClaimRoute:
    path: str
    view_name: str
    callback: object
    pattern: URLPattern


def flatten_claim_routes(patterns):
    return flatten_routes(patterns, include_path=_is_claim_reachable)


def flatten_routes(patterns, *, include_path=lambda _path: True):
    routes = []
    errors = []
    _flatten(
        patterns,
        route_prefix="",
        namespaces=(),
        routes=routes,
        errors=errors,
        include_path=include_path,
    )
    return routes, errors


def _flatten(patterns, *, route_prefix, namespaces, routes, errors, include_path):
    for pattern in patterns:
        path = f"{route_prefix}{pattern.pattern}"
        if isinstance(pattern, URLResolver):
            child_namespaces = namespaces
            if pattern.namespace:
                child_namespaces = (*namespaces, pattern.namespace)
            _flatten(
                pattern.url_patterns,
                route_prefix=path,
                namespaces=child_namespaces,
                routes=routes,
                errors=errors,
                include_path=include_path,
            )
            continue
        if not isinstance(pattern, URLPattern) or not include_path(path):
            continue
        if pattern.name is None:
            errors.append(f"Unnamed claim-reachable URL pattern: /{path}")
            continue
        if _is_catch_all(pattern):
            errors.append(f"Catch-all claim-reachable URL pattern: /{path}")
        qualified_name = ":".join((*namespaces, pattern.name))
        routes.append(
            ClaimRoute(
                path=f"/{path}",
                view_name=qualified_name,
                callback=pattern.callback,
                pattern=pattern,
            )
        )


def _is_claim_reachable(path):
    normalized = f"/{path.lstrip('/')}"
    return normalized.startswith(CLAIM_REACHABLE_PREFIXES)


def _is_catch_all(pattern):
    rendered = str(pattern.pattern)
    if "<path:" in rendered:
        return True
    if not isinstance(pattern.pattern, RegexPattern):
        return False
    return any(fragment in rendered for fragment in (".*", ".+"))


def handled_methods(route):
    callback = route.callback
    view_class = getattr(callback, "cls", None)
    if not inspect.isclass(view_class) or not issubclass(view_class, APIView):
        raise ValueError(
            f"{route.view_name} uses an uninspectable non-DRF callback"
        )
    _validate_callback_wrappers(route)
    actions = getattr(callback, "actions", None)
    if actions is not None:
        if not issubclass(view_class, ViewSetMixin):
            raise ValueError(f"{route.view_name} exposes unexpected ViewSet actions")
        methods = {method.upper() for method in actions}
    else:
        methods = {
            method.upper()
            for method in view_class.http_method_names
            if callable(getattr(view_class, method, None))
        }
    if "GET" in methods:
        methods.add("HEAD")
    if callable(getattr(view_class, "options", None)):
        methods.add("OPTIONS")
    return methods


def _validate_callback_wrappers(route):
    callback = route.callback
    seen = set()
    while callback is not None:
        if id(callback) in seen:
            raise ValueError(f"{route.view_name} has a cyclic callback wrapper")
        seen.add(id(callback))
        if getattr(callback, "__code__", None) not in _standard_callback_codes():
            raise ValueError(f"{route.view_name} uses an uninspectable callback wrapper")
        callback = getattr(callback, "__wrapped__", None)


@lru_cache(maxsize=1)
def _standard_callback_codes():
    class ProbeView(APIView):
        def get(self, request):  # pragma: no cover - never dispatched
            return None

    class ProbeViewSet(ViewSet):
        def list(self, request):  # pragma: no cover - never dispatched
            return None

    codes = set()
    callbacks = (ProbeView.as_view(), ProbeViewSet.as_view({"get": "list"}))
    for callback in callbacks:
        while callback is not None:
            codes.add(callback.__code__)
            callback = getattr(callback, "__wrapped__", None)
    return frozenset(codes)
