"""Per-space module-family visibility without removing the core loan spine."""


def module_family_features(feature_type):
    return (
        feature_type(
            "loans.enabled", "staff_admin", "Hardware loans",
            "Show the loan catalogue, borrowing and staff loan consoles. Turning this "
            "off preserves all loan data and core modules.", default_enabled=True,
        ),
    )
