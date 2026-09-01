"""Grouped module status for the console.

`/control/` is deliberately not proxied on the public frontend port, so without a React
surface the only ways to install a module are the shell and a Django admin screen a
non-technical operator cannot reach. This is the read side of that surface.

Everything here is DERIVED from `module_registry` and `module_install`. It holds no state
of its own, because a second source of truth for "is this installed" is exactly the drift
the registry exists to remove.
"""

from apps.makerspaces.module_install import module_status
from apps.makerspaces.module_registry import (
    GROUPS,
    BY_KEY,
    group_is_always_on,
    module_dependencies,
    with_dependencies,
)
from apps.makerspaces.platform import MODULE_WORKFLOWS
from apps.separability.tombstones import SEPARABLE_APPS, tombstoned_app_labels

# What each separable app actually costs an operator who does not use it. Written out
# rather than derived, because "what does this app give me" is not something the registry
# knows -- and an operator deciding whether to remove an app needs the answer in the
# terms they think in, not a list of module keys.
SEPARABLE_APP_NOTES = {
    "warranty": "Warranty tracking for assets, printers and machines.",
    "presence": "Geofenced check-in and presence sessions.",
    "payments": "Every online payment surface. Existing Payment rows are kept and stay readable.",
    "updates": "In-app release control. Remove it if your own tooling updates this box.",
    "events": "Event scheduling and registrations.",
    "bookings": "Resource booking and public self-booking.",
    "maintenance": "Maintenance schedules and work orders.",
    "procurement": "The to-buy list.",
    "roadmap": "Already tombstoned; retained for migration history only.",
}


def grouped_module_status(makerspace):
    """Every group with its modules, install state and what installing would pull in."""
    by_key = {row["key"]: row for row in module_status(makerspace)}
    dependencies = module_dependencies()
    groups = []
    for group in GROUPS:
        modules = []
        for key, definition in BY_KEY.items():
            if definition.group != group.key:
                continue
            row = dict(by_key[key])
            # What clicking Install would ALSO switch on. Shown before the click, because
            # a dependency resolved silently is a capability the operator did not choose.
            row["pulls_in"] = sorted(with_dependencies({key}) - {key})
            # What blocks Uninstall, computed against what is installed right now.
            row["required_by"] = sorted(
                other
                for other, requires in dependencies.items()
                if key in requires and by_key.get(other, {}).get("installed")
            )
            # The frontend workflows this key turns on, so a card can say what appears.
            row["workflows"] = list(MODULE_WORKFLOWS.get(key, ()))
            modules.append(row)
        installed = [row for row in modules if row["installed"]]
        groups.append(
            {
                "key": group.key,
                "label": group.label,
                "description": group.description,
                # A group holding a core key can never be switched off: core is added
                # back on every write, so a master toggle offering "off" would be a
                # control whose effect is silently undone.
                "always_on": group_is_always_on(group.key),
                "installed_count": len(installed),
                "module_count": len(modules),
                "modules": modules,
            }
        )
    return groups


def deployment_app_status():
    """Separable apps and whether this deployment ships them.

    READ-ONLY by design. `TOMBSTONED_APPS` is read at process start -- URL routing, admin
    registration and the OpenAPI schema are all built from it at import time -- so nothing
    the web process writes can take effect until a restart. A console that wrote the value
    would leave the running process disagreeing with the file, a state it could not report
    truthfully. It prints the line to paste instead.
    """
    tombstoned = tombstoned_app_labels()
    return {
        "apps": [
            {
                "app_label": app,
                "shipped": app not in tombstoned,
                "note": SEPARABLE_APP_NOTES.get(app, ""),
            }
            for app in sorted(SEPARABLE_APPS)
        ],
        "env_line": f"TOMBSTONED_APPS={','.join(sorted(tombstoned))}",
        "requires_restart": True,
    }
