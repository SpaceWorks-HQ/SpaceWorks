"""Direct machine-role grants and default scope seeding."""

from apps.accounts import rbac
from apps.accounts.rbac import Action

from .models_role_scope import RoleMachineTypeScope
from .role_scope_resolution import EXEMPT, manage_scope_for


def is_machine_only(actor, makerspace_id):
    """Whether the actor's authority here is machine-scoped and NOTHING else.

    The printing arm reads the stored grant via ``role_grants_directly`` because
    ``MANAGE_MACHINES`` implies ``MANAGE_PRINTING`` in effective RBAC authority.
    """
    if not rbac.can(actor, Action.MANAGE_MACHINES, makerspace_id):
        return False
    if manage_scope_for(actor, makerspace_id) is EXEMPT:
        return False
    if role_grants_directly(actor, makerspace_id, Action.MANAGE_PRINTING):
        return False
    return not (
        rbac.can(actor, Action.VIEW_INVENTORY, makerspace_id)
        or rbac.can(actor, Action.MANAGE_MAKERSPACE, makerspace_id)
    )


def grants_directly(actor, makerspace_id, action):
    """Whether the actor's role grants ``action`` outright, rather than by implication.

    Stored grants distinguish genuine type-manager authority from authority merely
    implied by ``MANAGE_MACHINES``; tier 1 applies machine links to the latter.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    if rbac._is_superadmin(actor):
        # Authority does not come from a role row, so no role can qualify it. Tier 1
        # already treats them as EXEMPT; agreeing here keeps the two consistent.
        return not rbac.superadmin_hidden_block_applies(actor, makerspace_id, action)
    return role_grants_directly(actor, makerspace_id, action)


def role_grants_directly(actor, makerspace_id, action):
    """Whether the actor's assigned ROLE stores ``action`` outright.

    Deliberately blind to superadmin status, unlike ``grants_directly``. This preserves
    a hidden-space superadmin's explicit machine-role narrowing.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    membership = actor.makerspace_memberships.select_related("assigned_role").filter(
        status="active", makerspace_id=makerspace_id
    ).first()
    if membership is None:
        return False
    if membership.assigned_role_id is None:
        return action in rbac._MEMBERSHIP_ROLE_ACTIONS.get(membership.role, ())
    role = membership.assigned_role
    if role.makerspace_id != membership.makerspace_id:
        return False
    granted = role.granted_actions if isinstance(role.granted_actions, list) else []
    return action in granted


def makerspaces_granting_directly(actor, action):
    """Query-level twin of :func:`grants_directly`: ids, or ``rbac.ALL``."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    if rbac._is_superadmin(actor):
        return rbac.makerspaces_for_action(actor, action)
    legacy_roles = [
        role
        for role, actions in rbac._MEMBERSHIP_ROLE_ACTIONS.items()
        if action in actions
    ]
    memberships = actor.makerspace_memberships.filter(status="active")
    scope = set(
        memberships.filter(
            assigned_role__isnull=False,
            assigned_role__granted_actions__contains=[action],
        ).values_list("makerspace_id", flat=True)
    )
    if legacy_roles:
        scope |= set(
            memberships.filter(
                assigned_role__isnull=True, role__in=legacy_roles
            ).values_list("makerspace_id", flat=True)
        )
    return rbac._exclude_archived_ids(scope)


def grant_builtin_type_scope(role):
    """Link a freshly seeded ``MANAGE_MACHINES`` role to all built-in types."""
    from .models import MachineType

    granted = role.granted_actions if isinstance(role.granted_actions, list) else []
    granted = {action for action in granted if isinstance(action, str)}
    if Action.MANAGE_MACHINES not in granted or Action.MANAGE_MAKERSPACE in granted:
        return
    RoleMachineTypeScope.objects.bulk_create(
        [
            RoleMachineTypeScope(role=role, machine_type_id=type_id)
            for type_id in MachineType.objects.filter(
                makerspace__isnull=True
            ).values_list("id", flat=True)
        ],
        ignore_conflicts=True,
    )
