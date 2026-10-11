"""Explicit WP4 field/model review, independent of other build lanes."""

EXPORTED_MODEL_FIELDS = {
    "machines.MachineMaterial": "id makerspace machine_type name colours is_active",
    "operations.StocktakePolicy": "id makerspace blind_default variance_threshold",
    "operations.StocktakeSchedule": "id makerspace container name interval_days next_due blind is_active",
}
FIELD_ADDITIONS = {
    "inventory.InventoryProduct": "borrowing_terms",
    "machines.Machine": "status_since public_fields",
    "machines.MachineType": "intake_schema",
    "operations.StocktakeSession": "blind variance_threshold approval_required",
    "maintenance.MaintenanceSchedule": "trigger usage_hours job_count meter_started_at",
}
OMITTED_MODELS = {
    "inventory.InventoryWatch": "Source personal delivery subscriptions do not become target disclosure authority.",
    "maintenance.MaintenanceCalendarFeed": "Deployment-local bearer authority; staff reissue a feed after import.",
}
NON_REFERENCE_JSON_FIELDS = frozenset({
    ("machines.Machine", "public_fields"),
    ("machines.MachineType", "intake_schema"),
    ("machines.MachineMaterial", "colours"),
})


def exported_fields(base):
    return {**{label: names + (" " + FIELD_ADDITIONS[label] if label in FIELD_ADDITIONS else "")
               for label, names in base.items()}, **EXPORTED_MODEL_FIELDS}
