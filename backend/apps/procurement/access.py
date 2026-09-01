"""Procurement access rules, derived from the existing RBAC action matrix.

No new permission action is introduced: a makerspace admin (MANAGE_MAKERSPACE,
held by Space Manager + Superadmin) owns both streams; hardware staff
(EDIT_INVENTORY) own the hardware stream; print managers (MANAGE_PRINTING) own
the printing stream. Visibility and write authority are both keyed off these."""
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.machines import role_scope
from apps.procurement.models import ToBuyItem

HARDWARE = ToBuyItem.Kind.HARDWARE
PRINTING = ToBuyItem.Kind.PRINTING


def viewable_kinds(actor, makerspace_id):
    """Streams the actor may see in this makerspace (admin sees both)."""
    if rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace_id):
        return [HARDWARE, PRINTING]
    kinds = []
    if rbac.can(actor, rbac.Action.EDIT_INVENTORY, makerspace_id):
        kinds.append(HARDWARE)
    if rbac.can(actor, rbac.Action.MANAGE_PRINTING, makerspace_id):
        kinds.append(PRINTING)
    return kinds


def can_use(actor, makerspace_id):
    """True if the actor has any procurement stream in this makerspace."""
    return bool(viewable_kinds(actor, makerspace_id))


def derive_kind(actor, makerspace_id, requested=None):
    """Decide the stream for a new item from the actor's role.

    Makerspace admins / superadmin may target either stream (default hardware);
    everyone else is auto-tagged: hardware staff -> hardware, print -> printing."""
    if rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace_id):
        return requested if requested in (HARDWARE, PRINTING) else HARDWARE
    if rbac.can(actor, rbac.Action.EDIT_INVENTORY, makerspace_id):
        return HARDWARE
    return PRINTING


def can_manage_kind(actor, makerspace_id, kind):
    """True if the actor may create/edit/delete items of this stream."""
    if kind == PRINTING:
        return rbac.can(actor, rbac.Action.MANAGE_PRINTING, makerspace_id)
    return rbac.can(actor, rbac.Action.EDIT_INVENTORY, makerspace_id)


def machine_type_scope(actor, makerspace_id):
    """Linked TYPE ids, or ``None`` when procurement is not narrowed at all.

    ``None`` and an empty set are different answers and must stay that way: ``None`` means
    "no narrowing", an empty set means "narrowed and reaches nothing" (a role holding
    `MANAGE_MACHINES` with no links, which fails closed). Callers must test ``is None``.

    Three ways out, in order:

    1. No ``MANAGE_MACHINES`` — this narrowing only ever applies to the authority machine
       scoping governs, so a plain Print Manager is untouched.
    2. Scope-EXEMPT — a space manager, a superadmin with no membership, or a
       null-`assigned_role` legacy membership. Checked before the next rule because a
       legacy role's frozen action set would otherwise answer the question below.
    3. The role **stores** ``MANAGE_PRINTING`` outright. What this phase closes is the leak
       through the **implied** grant: `IMPLIED_ACTIONS[MANAGE_MACHINES]` contains
       `MANAGE_PRINTING`, so a laser-scoped role silently inherited the whole printing
       stream. A role whose `granted_actions` really lists `manage_printing` was
       deliberately given that stream by an administrator, and taking it away because the
       role *also* picked up machine duties revokes an independent grant -- the same
       mistake as dropping a mixed role's inventory tiles from the dashboard. Read with
       `role_grants_directly`, not `grants_directly`, so superadmin status cannot stand in
       for a stored grant.
    """
    if not rbac.can(actor, rbac.Action.MANAGE_MACHINES, makerspace_id):
        return None
    scope = role_scope.manage_scope_for(actor, makerspace_id)
    if scope is role_scope.EXEMPT:
        return None
    if role_scope.role_grants_directly(
        actor, makerspace_id, rbac.Action.MANAGE_PRINTING
    ):
        return None
    type_ids, _machine_ids = scope
    return type_ids


def scope_items(queryset, actor, makerspace_id):
    """Apply stream and machine-type visibility for every To Buy surface.

    Hardware access is unchanged. Printing access inherited by a scoped
    ``MANAGE_MACHINES`` role reaches linked types only; NULL and per-machine-only
    authority deliberately reach no printing rows.
    """
    kinds = viewable_kinds(actor, makerspace_id)
    queryset = queryset.filter(makerspace_id=makerspace_id, kind__in=kinds)
    type_ids = machine_type_scope(actor, makerspace_id)
    if type_ids is None or PRINTING not in kinds:
        return queryset
    return queryset.filter(
        Q(kind=HARDWARE) | Q(kind=PRINTING, machine_type_id__in=type_ids)
    )


def provenance_machine_type_id(item):
    """The type the item's DURABLE provenance implies, or ``None``.

    Same ordering as migration `procurement/0007`'s backfill. The migration runs against
    historical models and cannot call this, so the order is deliberately stated in two
    places; changing one without the other makes a backfilled row disagree with what an
    edit is allowed to set.
    """
    if item.resulting_machine_id is not None:
        return item.resulting_machine.machine_type_id
    if item.source_pool_id is not None:
        if item.source_pool.machine_type_id is not None:
            return item.source_pool.machine_type_id
        if item.source_pool.machine_id is not None:
            return item.source_pool.machine.machine_type_id
    if item.resulting_pool_id is not None:
        if item.resulting_pool.machine_type_id is not None:
            return item.resulting_pool.machine_type_id
        if item.resulting_pool.machine_id is not None:
            return item.resulting_pool.machine.machine_type_id
    return None


def validate_machine_type_provenance(item, machine_type):
    """Refuse a retag that contradicts the machine the item actually came from.

    `machine_type` is an authorization label — `scope_items` decides who may read an
    item's vendor, cost, purchaser and receipts from it. So once a row is tied to a real
    machine or a machine-bound pool, letting it be relabelled (or cleared to the
    exempt-only NULL bucket) hides it from the team that owns that machine and shows it to
    another team, while contradicting the asset. The actor able to do this is scope-exempt
    and therefore trusted, which makes this an integrity rule rather than an escalation
    one: the label must keep describing the thing.

    Setting the value provenance already implies stays a no-op, and rows with no provenance
    are freely taggable, so nothing is trapped — a genuinely mislabelled row is corrected
    by fixing the provenance, not the label.
    """
    expected_id = provenance_machine_type_id(item)
    if expected_id is None:
        return
    given_id = machine_type.pk if machine_type is not None else None
    if given_id != expected_id:
        raise ValidationError(
            {
                "machine_type": (
                    "This item is tied to a machine, so its machine type follows that "
                    "machine and cannot be changed."
                )
            }
        )


def machine_type_is_required(actor, makerspace_id, requested_kind=None):
    """Whether this actor MUST name a machine type to create an item.

    Exactly the condition `validate_machine_type` enforces, exposed so the console can ask
    the server instead of re-deriving it from effective actions -- which cannot express a
    null-`assigned_role` legacy membership (exempt) and conflates "holds MANAGE_MACHINES"
    with "is narrowed by machine scope".
    """
    if derive_kind(actor, makerspace_id, requested_kind) != PRINTING:
        return False
    return machine_type_scope(actor, makerspace_id) is not None


def validate_machine_type(actor, makerspace_id, kind, machine_type):
    """Validate tenant ownership and scoped creation/update authority."""
    if machine_type is not None and machine_type.makerspace_id not in (None, makerspace_id):
        raise ValidationError(
            {"machine_type": "Machine type must belong to this makerspace."}
        )
    if kind != PRINTING:
        return
    type_ids = machine_type_scope(actor, makerspace_id)
    if type_ids is None:
        return
    if machine_type is None:
        raise ValidationError(
            {"machine_type": "This field is required for your machine scope."}
        )
    if machine_type.pk not in type_ids:
        raise ValidationError(
            {"machine_type": "You cannot procure for this machine type."}
        )


def scope_machine_type_options(queryset, actor, makerspace_id, requested_kind=None):
    """Machine types the actor may stamp on a newly created item."""
    queryset = queryset.filter(
        Q(makerspace_id=makerspace_id) | Q(makerspace__isnull=True)
    )
    kind = derive_kind(actor, makerspace_id, requested_kind)
    if kind != PRINTING:
        return queryset
    type_ids = machine_type_scope(actor, makerspace_id)
    if type_ids is None:
        return queryset
    return queryset.filter(pk__in=type_ids)
