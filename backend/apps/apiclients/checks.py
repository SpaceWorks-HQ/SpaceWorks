from django.core.checks import Error, Tags, register

from apps.apiclients.scope_registry import unregistered_protected_routes


@register(Tags.urls)
def check_scope_registry(app_configs=None, **_kwargs):
    missing = unregistered_protected_routes()
    if not missing:
        return []
    labels = [
        f"/{route} [{method or 'unknown method'}] ({view_name or 'unnamed route'})"
        for route, view_name, method in missing
    ]
    return [
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
