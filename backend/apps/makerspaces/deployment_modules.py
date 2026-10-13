"""Read identity module switches before a makerspace is selected.

Member sign-up, social login and mobile sessions use any live makerspace's
choice. Fresh installs remain able to bootstrap before a tenant exists.
"""

from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset

# The keys answered at deployment level, declared as a table rather than as three
# separate literal call sites. This is the `CHANNEL_MODULE_KEYS` shape: one gate shared
# by several keys, where the table IS the enforcement declaration that the registry
# drift guard reads. Un-DRYing it into one branch per key to satisfy the guard would be
# strictly worse code.
DEPLOYMENT_MODULE_KEYS = {
    "member_accounts": "member_accounts",
    "mobile_apps": "mobile",
}


def any_makerspace_enables(key):
    """Whether any live makerspace has ``key`` installed.

    Fails **OPEN** when there are no makerspaces at all. A fresh install before
    ``setup_instance`` has run has no tenant to consult, and the surfaces gated this way
    are exactly the ones needed to create the first one -- reading "no tenants" as
    "switched off" would make a new deployment unable to bootstrap itself.

    Archived makerspaces are excluded: an archived space is invisible everywhere but
    ``/control/``, so letting one keep a platform surface alive would make the surface
    outlive every space that asked for it.
    """
    from apps.makerspaces.models import Makerspace

    rows = list(
        servable_queryset().only("id", "enabled_modules")
    )
    if not rows:
        return True
    return any(module_enabled(makerspace, key) for makerspace in rows)


def mobile_module_enabled():
    """Whether this deployment offers native device sessions and push.

    Device login precedes makerspace selection (the native client sends
    ``X-Makerspace-Id`` only after it holds a grant), so like `member_accounts` this has no
    tenant to be scoped by at the moment it must be answered.
    """
    return any_makerspace_enables(DEPLOYMENT_MODULE_KEYS["mobile_apps"])


def member_accounts_enabled():
    """Whether this deployment offers member-facing accounts.

    Staff authentication is core RBAC and is never governed by this: a deployment that
    could switch off its own staff logins could not be administered.
    """
    return any_makerspace_enables(DEPLOYMENT_MODULE_KEYS["member_accounts"])
