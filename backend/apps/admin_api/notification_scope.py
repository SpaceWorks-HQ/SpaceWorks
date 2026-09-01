"""Shared scope-link editing for notification destinations and recipient rules.

Both carry the same three optional narrowings (machine type, machine, inventory category)
with the same semantics, so they share one writer rather than two that can drift. It works
on any row exposing the three related managers, which is what both models were given.
"""


class ScopeTargetError(Exception):
    """Raised when a save names a scope target this makerspace may not use."""

    def __init__(self, missing):
        super().__init__("Unknown scope target.")
        self.missing = missing


def resolve_scope_ids(model, ids, makerspace, *, allow_global=False):
    """Rows this makerspace may scope by, or raise naming the ids it may not.

    Unknown or foreign ids are an error rather than a silent drop: a save that quietly
    discards half the selection leaves an operator believing a rule is scoped when it is
    not. `allow_global` covers built-in machine types, which belong to no makerspace.
    """
    ids = list(dict.fromkeys(ids or []))
    if not ids:
        return []
    allowed = []
    for row in model.objects.filter(pk__in=ids):
        owner = row.makerspace_id
        if owner == makerspace.pk or (allow_global and owner is None):
            allowed.append(row)
    missing = sorted(set(ids) - {row.pk for row in allowed})
    if missing:
        raise ScopeTargetError(missing)
    return allowed


def apply_scope(row, scope, makerspace):
    """Replace a row's scope links.

    **Replace, not merge** — a merge makes unticking impossible. Passing `None` leaves the
    existing links untouched, which is what an edit that does not mention scope means.
    """
    if scope is None:
        return
    from apps.inventory.models import Category
    from apps.machines.models import Machine, MachineType

    types = resolve_scope_ids(
        MachineType, scope.get("machine_type_ids"), makerspace, allow_global=True
    )
    machines = resolve_scope_ids(Machine, scope.get("machine_ids"), makerspace)
    categories = resolve_scope_ids(Category, scope.get("category_ids"), makerspace)

    row.machine_type_scopes.all().delete()
    row.machine_scopes.all().delete()
    row.category_scopes.all().delete()
    for target in types:
        row.machine_type_scopes.create(machine_type=target)
    for target in machines:
        row.machine_scopes.create(machine=target)
    for target in categories:
        row.category_scopes.create(category=target)
