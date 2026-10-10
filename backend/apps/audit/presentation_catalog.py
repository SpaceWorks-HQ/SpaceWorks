"""Composition barrel for the audit presentation catalogue.

One entry per literal audit action, split into domain fragments so no file breaches the
size ceiling. Duplicates are refused at import: two fragments disagreeing about the same
action would make the disclosure policy depend on import order.
"""

from .presentation_catalog_accounts import ENTRIES as _ACCOUNTS
from .presentation_catalog_community import ENTRIES as _COMMUNITY
from .presentation_catalog_dynamic import (
    DENIED_ACTION_PREFIXES,
    DYNAMIC_EXACT_ACTIONS,
    NON_LITERAL_META_ACTIONS,
    WRAPPER_SITE_PREFIXES,
    is_denied,
)
from .presentation_catalog_hardware import ENTRIES as _HARDWARE
from .presentation_catalog_machines import ENTRIES as _MACHINES
from .presentation_catalog_makerspaces import ENTRIES as _MAKERSPACES
from .presentation_catalog_migration import ENTRIES as _MIGRATION
from .presentation_catalog_payments import ENTRIES as _PAYMENTS
from .presentation_catalog_platform import ENTRIES as _PLATFORM
from .presentation_catalog_types import AuditPresentation, P

# Closed name -> callable registry for target links. Phase 10 ships no resolver: a link
# needs a real route and query-level tenant authorization, which no generic one has.
LINK_RESOLVERS = {}

UNRECOGNIZED_LABEL = "Unrecognized audit action"


def _compose(*fragments):
    catalogue = {}
    for fragment in fragments:
        for entry in fragment:
            if entry.action in catalogue:
                raise ValueError(f"Duplicate audit presentation entry: {entry.action}")
            catalogue[entry.action] = entry
    return catalogue


PRESENTATION_CATALOG = _compose(
    _ACCOUNTS, _MAKERSPACES, _HARDWARE, _MACHINES, _COMMUNITY, _MIGRATION, _PAYMENTS,
    _PLATFORM,
)


__all__ = [
    "DENIED_ACTION_PREFIXES",
    "DYNAMIC_EXACT_ACTIONS",
    "LINK_RESOLVERS",
    "NON_LITERAL_META_ACTIONS",
    "PRESENTATION_CATALOG",
    "UNRECOGNIZED_LABEL",
    "WRAPPER_SITE_PREFIXES",
    "AuditPresentation",
    "P",
    "is_denied",
]
