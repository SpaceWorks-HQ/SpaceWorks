"""Deployment-level reading of a per-makerspace module key.

Two keys govern surfaces that have no makerspace to be scoped by:

* ``updates`` -- ``PlatformUpdateSettings`` is a ``pk=1`` singleton for the whole box,
  reached from a superadmin-only console. There is no tenant to ask.
* the platform half of ``accounts`` -- member sign-up, social sign-in and phone login
  all resolve *before* a makerspace is selected, which is the same reason social
  sign-in must never become a tenant feature.

A key that could not be read on those surfaces would be a switch with no effect, so
they are read as "does ANY active makerspace run this". On a single-tenant self-host --
the case these switches exist for, where the operator wants Inventory and Machines with
their own login and no in-app updater -- that is exactly the operator's own decision.
On managed hosting it means one tenant's choice reveals a superadmin-only surface,
which is not an escalation: the superadmin owns the platform either way.

This deliberately does NOT try to be per-tenant. Threading a makerspace id through the
update endpoints would let "whichever space you happen to be viewing" decide whether a
shared box may be updated, which is worse than a deployment-wide reading, not better.
"""

from apps.makerspaces.platform import module_enabled

# The keys answered at deployment level, declared as a table rather than as three
# separate literal call sites. This is the `CHANNEL_MODULE_KEYS` shape: one gate shared
# by several keys, where the table IS the enforcement declaration that the registry
# drift guard reads. Un-DRYing it into one branch per key to satisfy the guard would be
# strictly worse code.
DEPLOYMENT_MODULE_KEYS = {
    "in_app_updates": "updates",
    "member_accounts": "accounts",
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
        Makerspace.objects.filter(archived_at__isnull=True).only("id", "enabled_modules")
    )
    if not rows:
        return True
    return any(module_enabled(makerspace, key) for makerspace in rows)


def updates_module_enabled():
    """Whether this deployment ships in-app release control."""
    return any_makerspace_enables(DEPLOYMENT_MODULE_KEYS["in_app_updates"])


def mobile_module_enabled():
    """Whether this deployment offers native device sessions and push.

    Device login precedes makerspace selection (the native client sends
    ``X-Makerspace-Id`` only after it holds a grant), so like `accounts` this has no
    tenant to be scoped by at the moment it must be answered.
    """
    return any_makerspace_enables(DEPLOYMENT_MODULE_KEYS["mobile_apps"])


def member_accounts_enabled():
    """Whether this deployment offers member-facing accounts.

    Staff authentication is core RBAC and is never governed by this: a deployment that
    could switch off its own staff logins could not be administered.
    """
    return any_makerspace_enables(DEPLOYMENT_MODULE_KEYS["member_accounts"])
