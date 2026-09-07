"""Deployment editions: what this box is FOR, one level above modules.

The six core modules are the hardware loan spine and cannot be uninstalled (the Hard Rules
need a box scan and an issue photo to hand anything over), so an events-only or
bookings-only installation would otherwise still show a catalogue, a borrow flow and a
scanner it never uses. An edition **hides** a fixed set of module keys and makes their
public routes answer 404. It changes nothing else: `core_module_keys()`, `module_enabled()`
and every `require_module` gate are untouched, staff endpoints keep answering, migrations,
purge plans and backups are identical. That asymmetry is deliberate -- a hidden surface must
stay recoverable, and nothing recorded may become unreachable to staff.

`SPACEWORKS_EDITION` is a deployment-level setting, never per makerspace, read the same way
`member_accounts`/`updates` are read deployment-wide. `organization` is a labelling edition:
one makerspace row presented as "the organization"; tenancy is never re-anchored.
"""
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404

MAKERSPACE = "makerspace"
EVENTS = "events"
BOOKINGS = "bookings"
ORGANIZATION = "organization"

# Everything that only makes sense when the box lends hardware or runs machines.
_LOAN_AND_MACHINE_KEYS = frozenset({
    "public_inventory", "request_workflow", "scanner", "asset_units", "containers",
    "bulk_import", "stock_transfers", "qr_print_batches", "guest_handover", "procurement",
    "stocktake", "machines", "machine_service", "printing", "maintenance",
})


@dataclass(frozen=True)
class Edition:
    key: str
    label: str
    hidden_module_keys: frozenset
    # Which install profile setup should start from; `None` keeps the registry default.
    default_profile: str | None = None
    # The public home the frontend lands on for `/m/<slug>` (mirrors AppRoutes.tsx).
    public_home: str = "catalogue"
    organization_label: bool = False


EDITIONS = {
    MAKERSPACE: Edition(MAKERSPACE, "Makerspace", frozenset()),
    EVENTS: Edition(
        EVENTS, "Events", _LOAN_AND_MACHINE_KEYS | {"bookings"},
        default_profile="events", public_home="events",
    ),
    BOOKINGS: Edition(
        BOOKINGS, "Bookings", _LOAN_AND_MACHINE_KEYS | {"events"},
        default_profile="bookings", public_home="bookings",
    ),
    ORGANIZATION: Edition(ORGANIZATION, "Organization", frozenset(), organization_label=True),
}


def current_edition() -> Edition:
    key = (getattr(settings, "SPACEWORKS_EDITION", MAKERSPACE) or MAKERSPACE).strip().lower()
    try:
        return EDITIONS[key]
    except KeyError as exc:
        raise ImproperlyConfigured(
            f"SPACEWORKS_EDITION={key!r} is not an edition; choose one of {', '.join(sorted(EDITIONS))}."
        ) from exc


def hidden_module_keys() -> frozenset:
    return current_edition().hidden_module_keys


def public_surface_available(module_key: str) -> bool:
    """False when the edition hides this module's PUBLIC surface (staff surfaces stay)."""
    return module_key not in hidden_module_keys()


def require_public_surface(module_key: str) -> None:
    """404, not 403: a hidden public route does not exist as far as a visitor can tell."""
    if not public_surface_available(module_key):
        raise Http404
