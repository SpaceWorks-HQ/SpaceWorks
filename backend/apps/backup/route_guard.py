from django.urls import get_resolver

from apps.accounts.claim_route_inspection import flatten_routes, handled_methods
from apps.backup.route_policy import (
    QUARANTINE_ALLOWED,
    QUIESCED_ALLOWED,
    TARGET_IMPORT_ALLOWED,
)


# Inspection is deliberately limited to the recovery surface.  The runtime decision is
# still made solely from the resolved qualified name and method; these prefixes only stop
# unrelated Django-admin catch-alls from making the structural inspection impossible.
RECOVERY_ROUTE_PREFIXES = (
    "/api/v1/health/",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
    "/api/v1/recovery",
    "/api/v1/admin/platform/restores/",
)


class RecoveryRouteConfigurationError(AssertionError):
    pass


def validate_recovery_route_allowlists(patterns=None, *, policy_sets=None):
    """Prove every allowed (qualified view, method) pair exists and is inspectable."""
    patterns = patterns if patterns is not None else get_resolver().url_patterns
    routes, errors = flatten_routes(
        patterns,
        include_path=lambda path: f"/{path.lstrip('/')}".startswith(
            RECOVERY_ROUTE_PREFIXES
        ),
    )
    by_name = {}
    for route in routes:
        if route.view_name in by_name:
            errors.append(f"Duplicate qualified route name: {route.view_name}")
        by_name[route.view_name] = route

    policy_sets = policy_sets or (
        ("quarantined", QUARANTINE_ALLOWED),
        ("quiesced", QUIESCED_ALLOWED),
        ("target_import", TARGET_IMPORT_ALLOWED),
    )
    for mode, policies in policy_sets:
        names = {name for name, _method in policies}
        for name in names:
            if (name, "OPTIONS") not in policies:
                errors.append(f"{mode} route {name} has no explicit OPTIONS policy")
        for name, method in policies:
            route = by_name.get(name)
            if route is None:
                errors.append(f"{mode} allowlist route does not exist: {name} {method}")
                continue
            try:
                methods = handled_methods(route)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if method not in methods:
                errors.append(f"{mode} allowlist method is not handled: {name} {method}")
    if errors:
        raise RecoveryRouteConfigurationError("\n".join(errors))
    return routes
