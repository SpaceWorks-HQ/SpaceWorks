"""Write boundary for a role's machine scope links.

Lives in `apps.machines` rather than alongside `makerspaces.role_services` for two
reasons: the concern is machine-shaped (it validates against `MachineType`/`Machine`), and
when `machines` is tombstoned the ability to edit machine scope has to disappear with it
rather than linger as a management surface for an app that no longer has any.

`MANAGE_MAKERSPACE` is exempt from machine scoping, so there is no grant-ceiling check
here like `role_services._validate_actions` applies to action grants. The service still
revalidates that management authority under locks: an organization grant may disappear
after the view resolves the role but before this transaction starts.
"""

from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces import role_services

from .models import Machine, MachineType
from .models_role_scope import RoleMachineScope, RoleMachineTypeScope


def assignable_machine_types(makerspace):
    """Types a role in this makerspace may be scoped to: its own, plus global built-ins."""
    return MachineType.objects.filter(
        Q(makerspace_id=makerspace.pk) | Q(makerspace__isnull=True)
    ).order_by("name", "id")


def assignable_machines(makerspace):
    """Machines a role in this makerspace may be scoped to. Retired ones included.

    A retired machine still has service history, warranty and documents hanging off it,
    so a role may legitimately need to stay scoped to one; dropping it from the options
    would silently strip the link on the next save.
    """
    return Machine.objects.filter(makerspace_id=makerspace.pk).order_by("name", "id")


def current_scope(role):
    """The role's links, as two sorted id lists (the shape the console round-trips)."""
    return {
        "machine_type_ids": sorted(
            RoleMachineTypeScope.objects.filter(role=role).values_list(
                "machine_type_id", flat=True
            )
        ),
        "machine_ids": sorted(
            RoleMachineScope.objects.filter(role=role).values_list(
                "machine_id", flat=True
            )
        ),
    }


def _validated_ids(requested, allowed_queryset, field):
    requested = {int(value) for value in requested}
    if not requested:
        return set()
    allowed = set(allowed_queryset.values_list("id", flat=True))
    unknown = sorted(requested - allowed)
    if unknown:
        # Never silently drop: a save that quietly discards half the selection leaves the
        # administrator believing a team has access it does not have.
        raise serializers.ValidationError(
            {field: f"Not available in this makerspace: {unknown}."}
        )
    return requested


@transaction.atomic
def set_role_machine_scope(*, makerspace, role, actor, machine_type_ids, machine_ids):
    """Replace the role's links wholesale, under the same lock ordering as role edits.

    Makerspace row first, then the role — matching `role_services` exactly, because a
    concurrent role edit and a scope edit take both locks and a different order between
    them is a deadlock.

    Replace rather than merge: the console sends the full selection, and a merge would
    make unticking a box impossible.
    """
    from apps.makerspaces.models import Makerspace, MakerspaceRole

    makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
    role = MakerspaceRole.objects.select_for_update().get(
        pk=role.pk, makerspace=makerspace
    )
    actor_actions = role_services._locked_actor_actions(actor, makerspace)
    if rbac.Action.MANAGE_MAKERSPACE not in actor_actions:
        raise PermissionDenied()

    type_ids = _validated_ids(
        machine_type_ids, assignable_machine_types(makerspace), "machine_type_ids"
    )
    machine_pks = _validated_ids(
        machine_ids, assignable_machines(makerspace), "machine_ids"
    )

    before = current_scope(role)

    RoleMachineTypeScope.objects.filter(role=role).exclude(
        machine_type_id__in=type_ids
    ).delete()
    RoleMachineScope.objects.filter(role=role).exclude(
        machine_id__in=machine_pks
    ).delete()
    RoleMachineTypeScope.objects.bulk_create(
        [
            RoleMachineTypeScope(role=role, machine_type_id=type_id)
            for type_id in sorted(type_ids)
        ],
        ignore_conflicts=True,
    )
    RoleMachineScope.objects.bulk_create(
        [
            RoleMachineScope(role=role, machine_id=machine_id)
            for machine_id in sorted(machine_pks)
        ],
        ignore_conflicts=True,
    )

    after = current_scope(role)
    if after != before:
        # Machine scope is a permission boundary, so a change to it is auditable in its
        # own right — `role.updated` covers the action list and would not show this.
        audit.record(
            actor,
            "role.machine_scope_changed",
            makerspace=makerspace,
            target=role,
            meta={"before": before, "after": after},
        )
    return after
