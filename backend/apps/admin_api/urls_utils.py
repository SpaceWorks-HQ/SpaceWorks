from apps.separability.registry import runtime_active


def _separable(app_label, *routes):
    """Return routes only when their separable app is active."""
    return list(routes) if runtime_active(app_label) else []
