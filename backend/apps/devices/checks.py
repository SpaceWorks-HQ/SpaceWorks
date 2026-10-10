"""Startup guards: the device route registry must match the mounted URLconf exactly."""

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.urls import URLPattern, URLResolver, get_resolver

from apps.devices import route_registry

_IGNORED_METHODS = frozenset({"options", "head"})


def discover_device_routes(patterns=None, prefix="", namespaces=()):
    """{(qualified view name, METHOD): view class} for every route under device/."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    found = {}
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            namespace = (*namespaces, pattern.namespace) if pattern.namespace else namespaces
            found.update(discover_device_routes(pattern.url_patterns, route, namespace))
        elif isinstance(pattern, URLPattern) and route.startswith(route_registry.DEVICE_URL_PREFIX):
            view_class = getattr(pattern.callback, "view_class", None)
            name = ":".join((*namespaces, pattern.name or "<unnamed>"))
            methods = {
                method.upper()
                for method in getattr(view_class, "http_method_names", ())
                if method not in _IGNORED_METHODS and hasattr(view_class, method)
            }
            for method in methods or {"<none>"}:
                found[(name, method)] = view_class
    return found


def registry_errors(discovered, registry=route_registry.DEVICE_ROUTES):
    errors = []
    missing = sorted(set(discovered) - set(registry))
    stale = sorted(set(registry) - set(discovered))
    if missing:
        errors.append(f"device routes missing from the registry: {missing}")
    if stale:
        errors.append(f"stale device registry entries: {stale}")
    from apps.devices.authentication import DeviceAuthentication
    from apps.devices.permissions import DeviceRoutePermission

    expected_auth = {
        route_registry.ENROLLMENT_TOKEN: [],
        route_registry.DEVICE_SIGNATURE: [DeviceAuthentication],
    }
    for key in sorted(set(discovered) & set(registry)):
        entry, view_class = registry[key], discovered[key]
        if entry.auth_mode not in route_registry.AUTH_MODES:
            errors.append(f"{key} declares unknown auth mode {entry.auth_mode!r}")
            continue
        if list(getattr(view_class, "authentication_classes", ())) != expected_auth[entry.auth_mode]:
            errors.append(f"{key} authenticators do not match {entry.auth_mode}")
        if list(getattr(view_class, "permission_classes", ())) != [DeviceRoutePermission]:
            errors.append(f"{key} must use exactly DeviceRoutePermission")
    return errors


@register(Tags.urls)
def check_device_route_registry(app_configs=None, **kwargs):
    from apps.separability.registry import runtime_active

    if not runtime_active("devices"):
        return []
    return [
        Error(message, id="devices.E001") for message in registry_errors(discover_device_routes())
    ]


@register()
def check_device_protocol_settings(app_configs=None, **kwargs):
    skew = settings.DEVICE_SIGNATURE_MAX_SKEW_SECONDS
    nonce_ttl = settings.DEVICE_NONCE_TTL_SECONDS
    errors = []
    if skew < 1 or settings.DEVICE_ENROLLMENT_TTL_SECONDS < 1:
        errors.append(Error("Device skew and enrollment TTL must be positive.", id="devices.E002"))
    # A timestamp is accepted for 2 x skew seconds, so its nonce must outlive that window
    # or the same signed request becomes replayable once its nonce row is cleaned up.
    if nonce_ttl < 2 * skew:
        errors.append(Error(
            "DEVICE_NONCE_TTL_SECONDS must cover twice DEVICE_SIGNATURE_MAX_SKEW_SECONDS.",
            id="devices.E003",
        ))
    if settings.DEVICE_COMMAND_LEASE_SECONDS < 1 or settings.DEVICE_COMMAND_MAX_ATTEMPTS < 1:
        errors.append(Error("Device command lease and retry limit must be positive.", id="devices.E004"))
    return errors
