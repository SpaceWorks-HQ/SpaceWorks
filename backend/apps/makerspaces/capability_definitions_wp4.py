"""WP4 opt-ins; defaults preserve existing tenant behavior."""


def definitions(feature):
    return (
        feature("inventory.notify_when_back", "public_inventory", "Notify when back",
                requires_modules=("notifications",)),
        feature("stocktake.discipline", "stocktake", "Stocktake discipline"),
        feature("machines.public_detail", "machines", "Public machine details"),
        feature("machines.material_catalogue", "machines", "Local material catalogue"),
        feature("machines.structured_intake", "machine_service", "Structured machine intake",
                requires_modules=("machines",)),
        feature("maintenance.meters", "maintenance", "Usage-based maintenance",
                requires_modules=("machines",)),
        feature("maintenance.calendar_feed", "maintenance", "Maintenance calendar feed",
                requires_modules=("machines",)),
    )
