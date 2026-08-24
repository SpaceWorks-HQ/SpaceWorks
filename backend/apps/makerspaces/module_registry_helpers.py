def default_enabled_module_keys():
    """Enabled-by-default module keys for a new makerspace (a fresh list every call).

    Core is always included; everything else is opt-in and arrives via an install
    profile or `install_module`.

    Returned fresh because this backs a JSONField default: handing out the registry's
    own collection would let one makerspace's row mutate every future default.
    """
    return [
        definition.key
        for definition in MODULES
        if definition.default_enabled or definition.is_core
    ]


def core_module_keys():
    """Keys that are always on and must not be disabled."""
    return frozenset(definition.key for definition in MODULES if definition.is_core)


def module_workflows():
    """Frontend workflow names per module, for modules exposed to the frontend."""
    return {
        definition.key: list(definition.frontend_workflows)
        for definition in MODULES
        if definition.frontend_exposed and definition.frontend_workflows
    }


def modules_by_group():
    """Group key -> the modules under it, in registry order.

    The console renders this: one heading per group, the keys underneath. Returned
    fresh, and built from ``GROUPS`` rather than from the modules, so a group with no
    modules still appears (and so the order is the declared one, not hash order).
    """
    grouped = {group.key: [] for group in GROUPS}
    for definition in MODULES:
        grouped[definition.group].append(definition)
    return grouped


def group_for(key):
    """The group a module key belongs to, or ``None`` for an unknown legacy key.

    Unknown keys have no group for the same reason they stay frontend-exposed:
    ``_canonical_modules`` preserves them, and inventing a group would file a tenant's
    stored capability under a heading the registry knows nothing about.
    """
    definition = BY_KEY.get(key)
    return None if definition is None else definition.group


def group_module_keys(group_key):
    """Every module key under a group, core included."""
    return tuple(
        definition.key for definition in MODULES if definition.group == group_key
    )


def group_is_always_on(group_key):
    """Whether a group may be switched off at all.

    A group is always on when it is declared so, and also whenever it contains a core
    key -- the console must not offer a master toggle that ``_canonical_modules`` would
    silently undo by adding core back on the next write.
    """
    group = GROUPS_BY_KEY.get(group_key)
    if group is None:
        return False
    if group.always_on:
        return True
    return any(BY_KEY[key].is_core for key in group_module_keys(group_key))


def module_dependencies():
    """Module -> modules it requires."""
    return {
        definition.key: tuple(definition.requires_modules)
        for definition in MODULES
        if definition.requires_modules
    }


def with_dependencies(keys):
    """Expand keys to include everything they transitively require.

    Installing `printing` must pull in `machine_service`, or the install immediately
    fails the very dependency rule the registry declares.
    """
    resolved, queue = set(), list(keys)
    while queue:
        key = queue.pop()
        if key in resolved:
            continue
        resolved.add(key)
        definition = BY_KEY.get(key)
        if definition is not None:
            queue.extend(definition.requires_modules)
    return resolved


def dependents_of(key, among):
    """Which of `among` require `key` -- i.e. what breaks if `key` is removed."""
    return sorted(
        candidate
        for candidate in among
        if candidate in BY_KEY and key in BY_KEY[candidate].requires_modules
    )


def module_available(key):
    """Whether the app owning this module ships runtime surfaces in this deployment.

    Orthogonal to per-makerspace enablement, and deliberately not merged with it: a
    tombstoned app's key stays in a tenant's stored `enabled_modules` (uninstall
    retains data and is reversible, and a deployment-level decision must not rewrite
    tenant rows), but nothing the key names is reachable, so every consumer has to
    read it as off.

    Unknown legacy keys have no owning app and stay available, for the same reason
    `is_frontend_exposed` keeps them: filtering them out would silently drop a
    capability the registry has not learned about yet.
    """
    from apps.separability.registry import runtime_active

    definition = BY_KEY.get(key)
    return True if definition is None else runtime_active(definition.app_label)


def is_frontend_exposed(key):
    """Whether a key may appear in the bootstrap payload.

    Unknown (legacy) keys stay exposed: `_canonical_modules` deliberately preserves
    them, so filtering them out here would silently drop a tenant's stored capability.
    """
    definition = BY_KEY.get(key)
    return True if definition is None else definition.frontend_exposed


from apps.makerspaces.module_registry import (  # noqa: E402
    BY_KEY,
    GROUPS,
    GROUPS_BY_KEY,
    MODULES,
)
