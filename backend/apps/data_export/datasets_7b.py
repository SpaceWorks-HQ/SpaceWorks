"""Every printer row is anchored through its actual tenant, never a historical ID."""


def printer_dataset_specs(predicate):
    return {
        "devices.DeviceCommand": ("devices/commands.csv", predicate(("makerspace",), ("device__makerspace",))),
        "devices.PrinterDeviceBinding": ("devices/printer_bindings.csv", predicate(("makerspace",), ("device__makerspace",))),
        "devices.PrinterJob": ("devices/printer_jobs.csv", predicate(("makerspace",), ("device__makerspace", "command__makerspace"))),
        "devices.PrinterJobConsumption": ("devices/printer_consumptions.csv", predicate(("job__makerspace",))),
    }
