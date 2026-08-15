"""Build-failing validation for the complete claim-reachable route matrix."""

from django.conf import settings
from django.urls import get_resolver

from apps.accounts.claim_pre_auth_guard import (
    validate_claim_middleware,
    validate_pre_auth_route,
)
from apps.accounts.claim_route_inspection import flatten_claim_routes, handled_methods
from apps.accounts.claim_routes import CLAIM_ROUTES


class ClaimRouteConfigurationError(AssertionError):
    pass


def validate_claim_route_matrix(
    patterns=None,
    *,
    policies=None,
    require_all_active=True,
    check_middleware=True,
):
    """Return inspected routes or raise with every structural/policy drift found."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    if policies is None:
        policies = CLAIM_ROUTES
    errors = []
    if require_all_active and getattr(settings, "TOMBSTONED_APPS", frozenset()):
        errors.append("Claim route guard must run under the all-active app profile")
    wildcard_keys = [key for key in policies if key[1] == "*"]
    if wildcard_keys:
        errors.append(f"Claim route wildcards are forbidden: {wildcard_keys}")

    routes, flatten_errors = flatten_claim_routes(patterns)
    errors.extend(flatten_errors)
    names = {}
    actual_keys = set()
    for route in routes:
        previous = names.get(route.view_name)
        if previous is not None:
            errors.append(
                f"Duplicate qualified claim route name {route.view_name}: "
                f"{previous} and {route.path}"
            )
        else:
            names[route.view_name] = route.path
        try:
            methods = handled_methods(route)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errors.extend(validate_pre_auth_route(route))
        for method in methods:
            key = (route.view_name, method)
            actual_keys.add(key)
            if key not in policies:
                errors.append(f"Unclassified claim route: {route.view_name} {method}")

    stale = set(policies) - actual_keys
    if stale:
        errors.append(f"Claim matrix entries have no matching route/method: {sorted(stale)}")
    if check_middleware:
        errors.extend(validate_claim_middleware())
    if errors:
        raise ClaimRouteConfigurationError("\n".join(errors))
    return routes
