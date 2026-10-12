"""Import-time consistency checks over the module catalogue and its groups."""

from apps.makerspaces.module_registry_definitions import FEATURE_PARENT, GUARD, NONE


class ImproperlyConfiguredRegistry(Exception):
    """Raised at import time when the registry itself is inconsistent."""


def validate_registry(*, MODULES, BY_KEY, GROUPS, GROUPS_BY_KEY, GROUP_KEYS, group_module_keys):
    """Raise ImproperlyConfiguredRegistry on any inconsistency; called once at import."""
    if len(BY_KEY) != len(MODULES):
        seen, duplicates = set(), set()
        for definition in MODULES:
            (duplicates if definition.key in seen else seen).add(definition.key)
        raise ImproperlyConfiguredRegistry(f"Duplicate module keys: {sorted(duplicates)}.")
    for definition in MODULES:
        unknown = [key for key in definition.requires_modules if key not in BY_KEY]
        if unknown:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} requires unknown module(s): {', '.join(unknown)}."
            )
        if definition.is_core and definition.default_enabled:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} is core, which already implies default_enabled."
            )
        # A core module is present in EVERY makerspace and cannot be switched off. If it
        # declared a dependency on an optional key, either that key is really core (and
        # is mislabelled), or the core module stops working the moment an operator
        # uninstalls something they were told was optional. `9e496997` was that bug
        # without the declaration: core `request_workflow` hard-required a
        # MakerspaceMembership row, and the default `recommended` profile ships no
        # `membership` module -- so a fresh self-host install could not accept a public
        # borrow request at all. This catches the declared form of it at import time;
        # `tests/makerspaces/test_core_module_independence.py` covers the undeclared form.
        if definition.is_core:
            optional_requirements = [
                key
                for key in definition.requires_modules
                if key in BY_KEY and not BY_KEY[key].is_core
            ]
            if optional_requirements:
                raise ImproperlyConfiguredRegistry(
                    f"{definition.key} is core but requires optional module(s): "
                    f"{', '.join(sorted(optional_requirements))}. A core module must "
                    "work with every optional module uninstalled."
                )
        if definition.enforcement not in {GUARD, FEATURE_PARENT, NONE}:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} has unknown enforcement {definition.enforcement!r}."
            )
        if definition.group not in GROUP_KEYS:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} declares unknown group {definition.group!r}. "
                f"Known groups: {', '.join(sorted(GROUP_KEYS))}."
            )
    if len(GROUPS_BY_KEY) != len(GROUPS):
        raise ImproperlyConfiguredRegistry("Duplicate group keys.")
    for group in GROUPS:
        if not group.label or not group.description:
            raise ImproperlyConfiguredRegistry(f"Group {group.key} needs a label and description.")
        # An empty group renders as a heading an operator can click with nothing behind
        # it, which reads as a broken install rather than an unused one.
        if not group_module_keys(group.key):
            raise ImproperlyConfiguredRegistry(f"Group {group.key} contains no modules.")
    # A group declared always-on must actually be un-switchable, or the console would
    # offer a master toggle whose "off" position `_canonical_modules` immediately undoes.
    for group in GROUPS:
        if group.always_on and not any(BY_KEY[key].is_core for key in group_module_keys(group.key)):
            raise ImproperlyConfiguredRegistry(
                f"Group {group.key} claims always_on but holds no core module."
            )

