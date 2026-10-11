from .types import TenantPredicate as P

DATASET_SPECS = {
    "machines.MachineMaterial": ("machines/materials.csv", P(("makerspace",), ("machine_type__makerspace",))),
    "operations.StocktakePolicy": ("stocktake/policy.csv", P(("makerspace",))),
    "operations.StocktakeSchedule": ("stocktake/schedules.csv", P(("makerspace",), ("container__makerspace",))),
}
