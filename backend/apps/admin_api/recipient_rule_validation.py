"""Actor-aware validation of submitted recipient rules."""

from django.db.models import Q

from apps.admin_api.recipient_rule_common import (
    RuleValidationError,
    memberships_for,
)
from apps.integrations.models_recipients import NotificationRecipientKind
from apps.inventory.models import Category
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole

def _resolve_targets(makerspace, scope, *, delegated, reach):
    scope = scope or {}
    type_ids = set(scope.get("machine_type_ids") or [])
    machine_ids = set(scope.get("machine_ids") or [])
    category_ids = set(scope.get("category_ids") or [])
    if delegated and not (type_ids or machine_ids or category_ids):
        raise RuleValidationError("Delegated recipient rules require a machine scope.")

    types = list(
        MachineType.objects.filter(
            Q(makerspace__isnull=True) | Q(makerspace=makerspace), pk__in=type_ids
        )
    )
    machines = list(Machine.objects.filter(makerspace=makerspace, pk__in=machine_ids))
    categories = list(Category.objects.filter(makerspace=makerspace, pk__in=category_ids))
    missing = (
        type_ids - {row.pk for row in types}
        | machine_ids - {row.pk for row in machines}
        | category_ids - {row.pk for row in categories}
    )
    if delegated:
        missing |= type_ids - reach.type_ids
        missing |= {row.pk for row in machines if not reach.covers_machine(row)}
        # Machine-role scope has no category grant. A category is therefore never a
        # reachable maintenance target for a machine-only actor.
        missing |= category_ids
    if missing:
        raise RuleValidationError(
            "Unknown or unreachable scope target.", unknown=missing
        )
    return {"machine_types": types, "machines": machines, "categories": categories}


def _delegated_identities(makerspace, actor):
    """The role and user ids a delegated actor may name, as the picker offers them.

    Validated as well as offered. An endpoint that accepts identities its own editor never
    presents is the inverse of a list that 403s on click: the console shows the actor their
    own role and their teammates, so the API must refuse anything else rather than let a
    narrow grant direct another team's alerts at an arbitrary colleague.
    """
    membership = (
        MakerspaceMembership.objects.filter(
            makerspace=makerspace, user=actor, status="active"
        )
        .select_related("assigned_role")
        .first()
    )
    role_id = membership.assigned_role_id if membership else None
    if role_id is None:
        return frozenset(), frozenset()
    user_ids = frozenset(
        memberships_for(makerspace, assigned_role_id=role_id).values_list(
            "user_id", flat=True
        )
    )
    return frozenset({role_id}), user_ids


def prepare_rules(makerspace, rules, *, delegated, reach, actor=None):
    allowed_role_ids, allowed_user_ids = (
        _delegated_identities(makerspace, actor)
        if delegated
        else (frozenset(), frozenset())
    )
    prepared, seen = [], set()
    for rule in rules:
        kind = rule["kind"]
        role_id = rule.get("role_id")
        user_id = rule.get("user_id")
        if kind == NotificationRecipientKind.ROLE:
            if role_id is None:
                raise RuleValidationError("A role recipient needs a role.")
            if user_id is not None:
                raise RuleValidationError("A role recipient cannot also name a user.")
            if not MakerspaceRole.objects.filter(
                pk=role_id, makerspace=makerspace
            ).exists():
                raise RuleValidationError("Role must belong to this makerspace.")
            if delegated and role_id not in allowed_role_ids:
                raise RuleValidationError("You cannot select this role.")
            key = ("role", role_id)
        elif kind == NotificationRecipientKind.USER:
            if user_id is None:
                raise RuleValidationError("A named recipient needs a user.")
            if role_id is not None:
                raise RuleValidationError("A named recipient cannot also name a role.")
            if not MakerspaceMembership.objects.filter(
                makerspace=makerspace, user_id=user_id, status="active"
            ).exists():
                raise RuleValidationError(
                    "User must hold an active membership of this makerspace."
                )
            if delegated and user_id not in allowed_user_ids:
                raise RuleValidationError("You cannot select this member.")
            key = ("user", user_id)
        else:
            if role_id is not None or user_id is not None:
                raise RuleValidationError(
                    "Requester and all-member rows carry no role or user."
                )
            # `uniq_notification_recipient_special` is (makerspace, feature, event, kind),
            # so only ONE requester/members row can exist per event -- two teams wanting
            # "notify the requester for MY machines" are describing one shared row. These
            # kinds are therefore NOT created by delete-then-insert for a delegated actor:
            # `recipient_rule_merge` edits the shared row in place, replacing only the scope
            # links inside that delegate's reach, and `replace_recipient_rules` skips
            # creating the kinds it reports back. A link-less row covers EVERYTHING, so it
            # is refused there rather than narrowed. Nothing extra is needed here: the
            # submitted scope is already reach-validated by `_resolve_targets` below.
            key = (kind, None)
        if key in seen:
            raise RuleValidationError("Duplicate recipient in selection.")
        seen.add(key)
        prepared.append(
            {
                **rule,
                "scope_targets": _resolve_targets(
                    makerspace, rule.get("scope"), delegated=delegated, reach=reach
                ),
            }
        )
    return prepared
