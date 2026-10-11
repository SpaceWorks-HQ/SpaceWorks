"""Literal additions to the portable schema; credentials/subscriptions are dropped."""

from apps.data_export.classification_wp4 import EXPORTED_MODEL_FIELDS, FIELD_ADDITIONS

PROJECTED_LABELS = frozenset({"machines.MachineMaterial", "operations.StocktakePolicy", "operations.StocktakeSchedule"})
FIELD_NAMES = {
    "inventory.InventoryWatch": frozenset("id makerspace product user created_at ready_at notified_at".split()),
    "maintenance.MaintenanceCalendarFeed": frozenset("id makerspace user token_digest token_hint created_at revoked_at".split()),
    **{label: frozenset(names.split()) for label, names in EXPORTED_MODEL_FIELDS.items()},
}


def field_snapshot(base):
    return {**{label: names | frozenset(FIELD_ADDITIONS.get(label, "").split())
               for label, names in base.items()}, **FIELD_NAMES}
