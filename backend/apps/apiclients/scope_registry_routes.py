from dataclasses import dataclass
from types import MappingProxyType


PUBLIC_READ = "public:read"
PUBLIC_WRITE = "public:write"
PUBLIC_ALL = "public:*"
ADMIN_READ = "admin:read"
ADMIN_WRITE = "admin:write"
ADMIN_ALL = "admin:*"
REPORTS_READ = "reports:read"

TARGET_GLOBAL = "global"
TARGET_TENANT_SLUG = "tenant_slug"
TARGET_TENANT_TOKEN = "tenant_token"
TARGET_MODES = frozenset({TARGET_GLOBAL, TARGET_TENANT_SLUG, TARGET_TENANT_TOKEN})

PUBLIC_READ_SCOPES = frozenset({PUBLIC_READ, PUBLIC_ALL})
PUBLIC_WRITE_SCOPES = frozenset({PUBLIC_WRITE, PUBLIC_ALL})


@dataclass(frozen=True, slots=True)
class ScopeRegistryEntry:
    scopes: frozenset[str]
    target_mode: str
    tenant_apps_admitted: bool = False
    legacy_v1: bool = False


_READ = ("GET", "HEAD")
_WRITE = ("POST",)

# Each definition is (fully-qualified resolver view_name, concrete methods, scopes,
# target mode, tenant-app admission, legacy-v1 admission). Legacy admission is explicit
# so adding a route cannot silently widen the frozen cutover capability.
_ROUTE_DEFINITIONS = (
    ("public-makerspaces", _READ, PUBLIC_READ_SCOPES, TARGET_GLOBAL, True, True),
    ("v1:public-makerspaces", _READ, PUBLIC_READ_SCOPES, TARGET_GLOBAL, True, True),
    ("public-inventory", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-makerspace-stats", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-inventory-categories", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-inventory-detail", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("v1:public-inventory", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("v1:public-makerspace-stats", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("v1:public-inventory-categories", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("v1:public-inventory-detail", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-machines", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    (
        "public-machine-service-request-submit", _WRITE, PUBLIC_WRITE_SCOPES,
        TARGET_TENANT_SLUG, False, True,
    ),
    ("public-printer-service-queues", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-printer-service-pools", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-printer-service-upload", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False, True),
    (
        "public-printer-service-request", _WRITE, PUBLIC_WRITE_SCOPES,
        TARGET_TENANT_SLUG, False, True,
    ),
    ("public-event-list", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-organization-detail", _READ, PUBLIC_READ_SCOPES, TARGET_GLOBAL, True, True),
    ("public-organization-events", _READ, PUBLIC_READ_SCOPES, TARGET_GLOBAL, True, True),
    ("public-event-calendar", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-event-calendar-feed", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-event-register", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-event-feedback", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_TOKEN, False, True),
    ("public-event-feedback", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_TOKEN, False, True),
    ("public-bookable-space-list", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-space-availability", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-booking-submit", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("presence-start", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("presence-current", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("presence-end", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False, True),
    ("public-membership-request", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False, True),
    (
        "hardware_requests:request-submit", _WRITE, PUBLIC_WRITE_SCOPES,
        TARGET_TENANT_SLUG, False, True,
    ),
    (
        "hardware_requests:public-tool-evidence-url", _WRITE, PUBLIC_WRITE_SCOPES,
        TARGET_TENANT_SLUG, False, True,
    ),
    (
        "hardware_requests:public-tool-checkout", _WRITE, PUBLIC_WRITE_SCOPES,
        TARGET_TENANT_SLUG, False, True,
    ),
    (
        "hardware_requests:public-tool-return", _WRITE, PUBLIC_WRITE_SCOPES,
        TARGET_TENANT_SLUG, False, True,
    ),
    ("public-printer-service-status", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_TOKEN, False, True),
    (
        "hardware_requests:request-status", _READ, PUBLIC_READ_SCOPES,
        TARGET_TENANT_TOKEN, False, True,
    ),
)


def _build_registry():
    registry = {}
    for definition in _ROUTE_DEFINITIONS:
        view_name, methods, scopes, target_mode, tenant_apps_admitted, legacy_v1 = definition
        if target_mode not in TARGET_MODES:
            raise ValueError(f"Unknown API-client target mode: {target_mode}")
        entry = ScopeRegistryEntry(scopes, target_mode, tenant_apps_admitted, legacy_v1)
        for method in methods:
            key = (view_name, method)
            if key in registry:
                raise ValueError(f"Duplicate API-client scope registry key: {key}")
            registry[key] = entry
    return MappingProxyType(registry)


SCOPE_REGISTRY = _build_registry()
