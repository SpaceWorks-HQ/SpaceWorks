"""Deployment-level tombstoning of a separable app (plan B1/B5, decision D7).

Tombstoning is a **deployment** decision, not a per-makerspace one. URL routing,
admin registration and the OpenAPI schema are process-global: an app's runtime
surfaces are present for every tenant or absent for all of them. That is a
different question from the per-makerspace ``enabled_modules`` switch, which asks
whether a tenant uses a module the deployment ships — and the two compose, because
a module is usable only when both say yes.

``TOMBSTONED_APPS`` names **app labels, not module keys**. Several keys can share
one app (``printing``, ``machines`` and ``machine_service`` all live in
``apps.machines``), and it is the app's code that is being removed.

Tombstoning never touches data. Rows stay, migrations stay installed, and the
retention registry keeps its purge plans and PII mappings — see ``registry`` for
why deregistering those would strand private objects and plaintext PII. Reversing a
tombstone is deleting the label from the setting; nothing has to be restored.
"""

import os

from apps.separability.registry import register_runtime_app, registered_runtime_apps

# The apps that have been made separable, one per phase of plan B6. Declared rather
# than derived: separability is a decision about whether an app's surfaces can be
# removed without leaving the rest of the system incoherent, and nothing in the module
# registry encodes that. `is_core` comes closest and is not the same question --
# `apps.makerspaces` owns only non-core modules and is the tenant root, while
# `apps.inventory` owns a core module *and* two optional ones.
#
# Anything named in TOMBSTONED_APPS but absent here is refused at startup
# (separability.E007), so a typo, a dotted path or a core app cannot quietly read as a
# working tombstone.
SEPARABLE_APPS = frozenset({
    "procurement", "notifications", "warranty", "maintenance", "presence", "events", "bookings",
})


def unavailable_apps():
    """Separable apps this deployment does not ship, for clients that must hide UI.

    Most console tabs are gated by a module key, and `platform.available_modules`
    already drops a tombstoned app's key -- so most of the frontend needs nothing.
    This exists for the apps that own **no module key of their own**: `warranty` is
    gated by core `staff_admin` and `presence` by no module at all, so there is no key
    to drop and their tabs would survive the tombstone and 404 on every request. B5
    named warranty as the most exposed case for exactly this reason.

    Deployment-global, so it is emitted **omitted-when-empty**: an untombstoned
    deployment's payloads stay byte-for-byte what they were, the same discipline the
    `geofence_enabled` bootstrap flag follows.
    """
    from apps.separability.registry import runtime_active

    return sorted(app for app in SEPARABLE_APPS if not runtime_active(app))


def tombstoned_app_labels():
    """Parse the deployment's tombstone list. The one parser; everything else reads it.

    Read from the environment rather than from settings because the earliest consumer
    is ``config/unfold.py``, which settings *imports* — it cannot import settings
    back. ``settings.TOMBSTONED_APPS`` is assigned from this function, so there is a
    single spelling of the parse and the two can never disagree.
    """
    raw = os.environ.get("TOMBSTONED_APPS", "")
    return frozenset(label.strip() for label in raw.split(",") if label.strip())


def app_is_tombstoned(app_label):
    """Read the setting directly, bypassing the runtime manifest.

    Almost every caller wants ``registry.runtime_active`` instead: it is the
    post-startup answer and it also knows about the permanently tombstoned apps that
    no setting names. Use this only where the manifest is not populated yet.

    That is a real case, not a hypothetical: ``django.contrib.admin`` sits above every
    ``apps.*`` entry in ``INSTALLED_APPS``, so its ``ready()`` autodiscovers every
    ``admin.py`` *before* the owning app's ``ready()`` has registered anything. An
    ``admin.py`` asking the manifest would be told "active" during a tombstoned boot
    and would register its models anyway. Both answers derive from the same setting,
    so they cannot disagree.
    """
    from django.conf import settings

    return app_label in getattr(settings, "TOMBSTONED_APPS", frozenset())


def register_separable_app(app_label):
    """Publish an app's runtime state into the manifest. Call from ``ready()``.

    Idempotent: ``ready()`` can run more than once in a process that reloads app
    configs, and duplicate registration is fatal by design.

    Query-free, as ``ready()`` requires — it reads one setting and touches no
    database.
    """
    if app_label in registered_runtime_apps():
        return
    register_runtime_app(app_label, tombstoned=app_is_tombstoned(app_label))
