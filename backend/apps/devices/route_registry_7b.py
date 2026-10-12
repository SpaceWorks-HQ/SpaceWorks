"""Exact phase 7b routes, composed using the existing registry vocabulary."""


def printer_routes(route_type, signature_mode, all_kinds):
    return {
        ("devices:device-command-lease", "POST"): route_type(signature_mode, "commands.lease", all_kinds, ("devices",)),
        ("devices:device-command-ack", "POST"): route_type(signature_mode, "commands.ack", all_kinds, ("devices",)),
        ("devices:device-printer-job-telemetry", "POST"): route_type(signature_mode, "printer.telemetry", frozenset({"printer"}), ("devices", "machines", "machine_service")),
        ("devices:device-printer-job-result", "POST"): route_type(signature_mode, "printer.result", frozenset({"printer"}), ("devices", "machines", "machine_service")),
    }
