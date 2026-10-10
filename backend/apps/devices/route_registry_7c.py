"""Exact label routes; constructed by the route registry after its types exist."""


def label_routes(route, signed_mode):
    kinds = frozenset({"label_printer"})
    modules = ("devices", "qr_print_batches")
    return {
        ("devices:device-label-command-content", "GET"): route(signed_mode, "labels.content", kinds, modules),
        ("devices:device-label-command-result", "POST"): route(signed_mode, "labels.result", kinds, modules),
    }
