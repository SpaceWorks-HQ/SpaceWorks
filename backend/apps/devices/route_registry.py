"""The authoritative registry of every ``/api/v1/device/`` route a device may call.

This is a principal-specific registry, deliberately separate from the HMAC API-client
scope registry (``apps/apiclients/scope_registry*``): a device is a different principal
with a different wire protocol. Entries are keyed by exact (qualified URL name, HTTP
method). ``checks.check_device_route_registry`` refuses startup on a missing, stale or
method-drifted entry, or a view whose authenticators do not match its declared mode;
``permissions.DeviceRoutePermission`` denies anything unlisted before view logic.
"""

from dataclasses import dataclass

ENROLLMENT_TOKEN = "enrollment_token"
DEVICE_SIGNATURE = "device_signature"
AUTH_MODES = frozenset({ENROLLMENT_TOKEN, DEVICE_SIGNATURE})
DEVICE_URL_PREFIX = "api/v1/device/"
ALL_KINDS = frozenset({"printer", "label_printer", "generic"})


@dataclass(frozen=True)
class DeviceRoute:
    auth_mode: str
    action: str
    kinds: frozenset
    # All-of: every listed module must be enabled for the device's makerspace.
    modules: tuple


DEVICE_ROUTES = {
    ("devices:device-enrollment-challenge", "POST"): DeviceRoute(
        ENROLLMENT_TOKEN, "enrollment.challenge", ALL_KINDS, ("devices",)
    ),
    ("devices:device-enrollment-complete", "POST"): DeviceRoute(
        ENROLLMENT_TOKEN, "enrollment.complete", ALL_KINDS, ("devices",)
    ),
    ("devices:device-heartbeat", "POST"): DeviceRoute(
        DEVICE_SIGNATURE, "heartbeat", ALL_KINDS, ("devices",)
    ),
}


def entry_for(request):
    match = getattr(request, "resolver_match", None)
    view_name = getattr(match, "view_name", None)
    return DEVICE_ROUTES.get((view_name, request.method))
