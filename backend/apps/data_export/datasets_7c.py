from .types import TenantPredicate

LABEL_DATASET_SPECS = {
    "devices.LabelPrintCommand": ("devices/label_commands.csv", TenantPredicate(("makerspace",),
        ("device__makerspace", "command__makerspace", "batch__makerspace"))),
    "devices.LabelPrintResult": ("devices/label_results.csv", TenantPredicate(("makerspace",),
        ("label_command__makerspace",))),
}
