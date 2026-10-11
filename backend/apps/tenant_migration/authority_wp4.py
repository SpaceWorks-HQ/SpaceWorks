from .tenant_dump_types import AuthorityDisposition as D, authority


def fields(label, names, disposition):
    return tuple(((label, name), authority(disposition,
                 "WP4 tenant data retains target module, feature and actor gates.")) for name in names.split())


AUTHORITY_ENTRIES = (
    *fields("inventory.InventoryProduct", "borrowing_terms", D.PRESERVE),
    *fields("inventory.InventoryWatch", "makerspace product user ready_at notified_at", D.DROP),
    *fields("maintenance.MaintenanceCalendarFeed", "makerspace user token_digest token_hint revoked_at", D.DROP),
    *fields("machines.Machine", "status_since", D.PRESERVE),
    *fields("machines.Machine", "public_fields", D.RESET),
    *fields("machines.MachineType", "intake_schema", D.PRESERVE),
    *fields("machines.MachineMaterial", "makerspace machine_type name colours is_active", D.PRESERVE),
    *fields("operations.StocktakePolicy", "makerspace blind_default", D.PRESERVE),
    *fields("operations.StocktakePolicy", "variance_threshold", D.RESET),
    *fields("operations.StocktakeSchedule", "makerspace container name interval_days next_due blind", D.PRESERVE),
    *fields("operations.StocktakeSchedule", "is_active", D.RESET),
    *fields("operations.StocktakeSession", "blind", D.PRESERVE),
    *fields("operations.StocktakeSession", "variance_threshold approval_required", D.RESET),
    *fields("maintenance.MaintenanceSchedule", "trigger usage_hours job_count meter_started_at", D.PRESERVE),
)

AUTHORITY_FIELDS = {edge: rule.reason for edge, rule in AUTHORITY_ENTRIES}
