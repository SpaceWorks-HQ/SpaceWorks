"""Shared primitives for recipient-rule administration.

A neutral module so the visibility half (`recipient_rule_access`) and the validation half
(`recipient_rule_validation`) can both depend on it without importing each other — the
circular-import shape that a barrel split otherwise walks straight into.
"""

from dataclasses import dataclass

from apps.accounts.models import User
from apps.integrations.models_recipients import NotificationRecipient
from apps.machines import role_scope
from apps.makerspaces.models import MakerspaceMembership


class RuleValidationError(Exception):
    def __init__(self, detail, *, unknown=None):
        super().__init__(detail)
        self.detail = detail
        self.unknown = sorted(set(unknown or []))


@dataclass(frozen=True)
class MachineReach:
    type_ids: frozenset[int]
    machine_ids: frozenset[int]

    def covers_machine(self, machine):
        return machine.pk in self.machine_ids or machine.machine_type_id in self.type_ids


def reach_for(actor, makerspace_id):
    """The actor's machine reach, or ``None`` when they are scope-EXEMPT."""
    scope = role_scope.manage_scope_for(actor, makerspace_id)
    if scope is role_scope.EXEMPT:
        return None
    return MachineReach(*scope)


def rows_for(makerspace, *, feature=None, event=None):
    filters = {"makerspace": makerspace}
    if feature is not None:
        filters["feature"] = feature
    if event is not None:
        filters["event"] = event
    return NotificationRecipient.objects.filter(**filters).prefetch_related(
        "machine_scopes__machine",
        "machine_type_scopes__machine_type",
        "category_scopes",
    )


def row_fully_reachable(row, reach, *, manageable_identity=None):
    """Whether the actor's reach covers EVERY target this row names.

    A row with **no** scope links returns False: it is a space-wide policy, which a
    delegated actor must never be able to delete or overwrite. Any category link also
    returns False, because `manage_scope_for` grants no category reach and there is
    therefore nothing to check it against -- fail closed.

    **Scope reach is not sufficient on its own.** A Space Manager may legitimately write a
    laser-scoped rule naming a role or member the delegate cannot manage; returning it as
    editable made the read disagree with the write, because `prepare_rules` accepts only
    the delegate's own role and its holders. The delegate then could not round-trip their
    own PUT without deleting the manager's policy. `manageable_identity` closes that: a row
    is editable only when its scope is reachable AND its identity is one this actor may
    write, so anything else is preserved as an identity-free marker instead.
    """
    types = [link.machine_type for link in row.machine_type_scopes.all()]
    type_ids = {machine_type.pk for machine_type in types}
    machines = [link.machine for link in row.machine_scopes.all()]
    category_ids = {link.category_id for link in row.category_scopes.all()}
    if not (type_ids or machines or category_ids):
        return False
    if manageable_identity is not None and not manageable_identity(row):
        return False
    return (
        not category_ids
        and all(
            machine_type.makerspace_id in (None, row.makerspace_id)
            for machine_type in types
        )
        and all(machine.makerspace_id == row.makerspace_id for machine in machines)
        and type_ids <= reach.type_ids
        and all(reach.covers_machine(machine) for machine in machines)
    )


def memberships_for(makerspace, *, assigned_role_id=None):
    filters = {
        "makerspace": makerspace,
        "status": "active",
        "user__is_active": True,
        "user__access_status": User.AccessStatus.ACTIVE,
    }
    if assigned_role_id is not None:
        filters["assigned_role_id"] = assigned_role_id
    return (
        MakerspaceMembership.objects.filter(**filters)
        .exclude(user__is_superuser=True)
        .select_related("user")
        .order_by("user__username")
    )
