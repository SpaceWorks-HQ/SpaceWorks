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


_READ = ("GET", "HEAD")
_WRITE = ("POST",)

# Each definition is (fully-qualified resolver view_name, concrete methods, scopes,
# target mode, tenant-app admission). Expanding the method tuple keeps the public table
# keyed exactly by (view_name, method) without repeating identical route metadata.
_ROUTE_DEFINITIONS = (
    ("public-makerspaces", _READ, PUBLIC_READ_SCOPES, TARGET_GLOBAL, False),
    ("v1:public-makerspaces", _READ, PUBLIC_READ_SCOPES, TARGET_GLOBAL, False),
    ("public-inventory", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-makerspace-stats", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-inventory-categories", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-inventory-detail", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("v1:public-inventory", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("v1:public-makerspace-stats", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("v1:public-inventory-categories", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("v1:public-inventory-detail", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-machines", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-machine-service-request-submit", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-printer-service-queues", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-printer-service-pools", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-printer-service-upload", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-printer-service-request", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-event-list", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-event-register", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-bookable-space-list", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-space-availability", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-booking-submit", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("presence-start", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("presence-current", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_SLUG, False),
    ("presence-end", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-membership-request", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("hardware_requests:request-submit", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("hardware_requests:public-tool-evidence-url", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("hardware_requests:public-tool-checkout", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("hardware_requests:public-tool-return", _WRITE, PUBLIC_WRITE_SCOPES, TARGET_TENANT_SLUG, False),
    ("public-printer-service-status", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_TOKEN, False),
    ("hardware_requests:request-status", _READ, PUBLIC_READ_SCOPES, TARGET_TENANT_TOKEN, False),
)


def _build_registry():
    registry = {}
    for view_name, methods, scopes, target_mode, tenant_apps_admitted in _ROUTE_DEFINITIONS:
        if target_mode not in TARGET_MODES:
            raise ValueError(f"Unknown API-client target mode: {target_mode}")
        entry = ScopeRegistryEntry(scopes, target_mode, tenant_apps_admitted)
        for method in methods:
            key = (view_name, method)
            if key in registry:
                raise ValueError(f"Duplicate API-client scope registry key: {key}")
            registry[key] = entry
    return MappingProxyType(registry)


SCOPE_REGISTRY = _build_registry()
