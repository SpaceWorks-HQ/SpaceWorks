from django.core.checks import Error, Tags, register

from apps.apiclients.scope_registry import (
    LEGACY_SCOPE,
    SCOPE_REGISTRY,
    SCOPE_VOCABULARY,
    unregistered_protected_routes,
)


@register(Tags.urls)
def check_scope_registry(app_configs=None, **_kwargs):
    errors = []
    used = frozenset(scope for entry in SCOPE_REGISTRY.values() for scope in entry.scopes)
    unknown = used - SCOPE_VOCABULARY
    unused = SCOPE_VOCABULARY - used - {LEGACY_SCOPE}
    if unknown or unused:
        errors.append(Error(
            "API-client scope vocabulary disagrees with the route registry: "
            f"unknown={sorted(unknown)}, unused={sorted(unused)}.",
            hint="Every supported scope must authorize a registered route.",
            id="apiclients.E002",
        ))
    missing = unregistered_protected_routes()
    if not missing:
        return errors
    labels = [
        f"/{route} [{method or 'unknown method'}] ({view_name or 'unnamed route'})"
        for route, view_name, method in missing
    ]
    return errors + [
        Error(
            "HMAC-protected routes are missing API-client scope registry entries: "
            + "; ".join(labels),
            hint=(
                "Register every route/method before widening "
                "HMAC_PROTECTED_PATH_PREFIXES."
            ),
            id="apiclients.E001",
        )
    ]
