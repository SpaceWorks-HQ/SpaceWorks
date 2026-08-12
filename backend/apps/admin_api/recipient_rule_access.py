"""Actor-aware visibility and payload construction for recipient-rule administration."""

from collections import Counter

from django.db.models import Q

from apps.admin_api.recipient_rule_common import (
    memberships_for,
    row_fully_reachable,
    rows_for,
)
from apps.admin_api.recipient_rule_merge import SHARED_KINDS, owned_links
from apps.integrations import notification_catalog, recipients as recipient_selection
from apps.integrations.notification_enums import NotificationFeature
from apps.integrations.models_recipients import NotificationRecipientKind
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole

SELECTABLE = sorted(recipient_selection.SELECTABLE_FEATURES)


def serialize_rule(row):
    return {
        "id": row.pk,
        "feature": row.feature,
        "event": row.event,
        "kind": row.kind,
        "role_id": row.role_id,
        "user_id": row.user_id,
        "scope": {
            "machine_type_ids": [
                link.machine_type_id for link in row.machine_type_scopes.all()
            ],
            "machine_ids": [link.machine_id for link in row.machine_scopes.all()],
            "category_ids": [link.category_id for link in row.category_scopes.all()],
        },
    }


def project_special_row(row, reach):
    """A shared `requester`/`members` row reduced to the links this delegate owns.

    A row of these kinds that carries links both inside and outside the delegate's reach is
    not fully reachable, so `payload` would hide it -- and after `recipient_rule_merge`
    writes the delegate's links into it, their successful save would read back as absent.
    That is the same "a save that looks dropped" defect the merge exists to remove, one
    level further down. The delegate is therefore shown exactly their own portion.

    Two rules hold this together:

    * **It shares `owned_links` with the merge.** Showing one set of links and stripping a
      different one would make an untouched form silently add or drop coverage on save.
    * **`id` is `None`.** PUT is not id-addressed (`RecipientRulesPutSerializer` carries no
      `id`), so the real primary key confers no power -- but it is still a disclosure about
      a row the delegate does not own, and nothing reads it: the console keys the list by
      index and `toDraft` drops the field.

    No identity is exposed because these two kinds carry none. The out-of-reach remainder
    stays counted in `managed_policy_markers`.
    """
    type_links, machine_links = owned_links(row, reach)
    return {
        "id": None,
        "feature": row.feature,
        "event": row.event,
        "kind": row.kind,
        "role_id": None,
        "user_id": None,
        "scope": {
            "machine_type_ids": [link.machine_type_id for link in type_links],
            "machine_ids": [link.machine_id for link in machine_links],
            "category_ids": [],
        },
    }


def _partially_owned_special(row, reach):
    """Is this a shared-kind row the delegate owns part, but not all, of?

    A row with **no** links is excluded: that is a space-wide policy covering everything,
    which a delegate may neither narrow nor project -- `recipient_rule_merge` refuses to
    write it and it stays a marker.
    """
    if row.kind not in SHARED_KINDS or reach is None:
        return False
    type_links, machine_links = owned_links(row, reach)
    return bool(type_links or machine_links)


def _features(makerspace, delegated):
    offered = [NotificationFeature.MAINTENANCE] if delegated else SELECTABLE
    return [
        {
            "key": feature,
            "events": list(notification_catalog.FEATURE_EVENTS.get(feature, ())),
        }
        for feature in offered
        if recipient_selection.feature_available(makerspace, feature)
    ]


def _manageable_identity(makerspace, actor):
    """Predicate for "may this delegate write a row naming this identity".

    Built from the same two facts `_identity_options` offers a delegate -- their own
    assigned role, and the members holding it -- so the editable set and the picker cannot
    drift apart.

    **`requester` and `members` rows ARE manageable, and that is a deliberate reversal.**
    They name no identity at all (`requester` is whoever raised the alert, `members` is
    everybody), so there is no identity to gate and scope is the only question -- which
    `row_fully_reachable` already answers. Refusing them made a delegate unable to
    round-trip their own save: `payload` hid the row and their PUT was rejected, so the
    capability the design intends (a per-team "notify the requester for laser alerts"
    policy) was unreachable. A row of these kinds that is only PARTLY inside the delegate's
    reach is still not fully reachable; it is shown redacted by `project_special_row` and
    edited in place by `recipient_rule_merge`.

    **The consequence, accepted rather than overlooked: for these two kinds SCOPE IS
    OWNERSHIP and `created_by` is never consulted.** A delegate can therefore delete a
    Space Manager's `requester` row when every link on it lies inside their reach. That is
    already the contract for a `role` row naming the delegate's own role, and the schema
    carries no per-link contributor provenance to express anything finer
    (`RecipientMachineTypeScope` is `(recipient, machine_type)` and nothing more). Pinned
    by `test_delegate_may_delete_a_manager_special_row_inside_their_reach`.
    """
    membership = (
        MakerspaceMembership.objects.filter(
            makerspace=makerspace, user=actor, status="active"
        )
        .select_related("assigned_role")
        .first()
    )
    role_id = membership.assigned_role_id if membership else None
    member_ids = (
        {row.user_id for row in memberships_for(makerspace, assigned_role_id=role_id)}
        if role_id
        else set()
    )

    def manageable(row):
        if row.kind == NotificationRecipientKind.ROLE:
            return role_id is not None and row.role_id == role_id
        if row.kind == NotificationRecipientKind.USER:
            return row.user_id in member_ids
        # requester / members: no identity to gate. See the docstring.
        return True

    return manageable


def _identity_options(makerspace, actor, delegated):
    if delegated:
        membership = (
            MakerspaceMembership.objects.filter(
                makerspace=makerspace, user=actor, status="active"
            )
            .select_related("assigned_role")
            .first()
        )
        role_ids = (
            [membership.assigned_role_id]
            if membership and membership.assigned_role_id
            else []
        )
        roles = MakerspaceRole.objects.filter(pk__in=role_ids, makerspace=makerspace)
        members = (
            memberships_for(
                makerspace,
                assigned_role_id=membership.assigned_role_id if membership else None,
            )
            if role_ids
            else []
        )
    else:
        roles = MakerspaceRole.objects.filter(makerspace=makerspace).order_by("name")
        members = memberships_for(makerspace)
    return (
        [{"id": row.pk, "name": row.name, "slug": row.slug} for row in roles],
        [
            {
                "id": membership.user_id,
                "username": membership.user.username,
                "email": membership.user.email,
            }
            for membership in members
        ],
    )


def _scope_options(makerspace, reach):
    if reach is None:
        return {"machine_types": [], "machines": [], "categories": []}
    types = MachineType.objects.filter(
        Q(makerspace__isnull=True) | Q(makerspace=makerspace), pk__in=reach.type_ids
    ).order_by("name")
    machines = Machine.objects.filter(makerspace=makerspace).filter(
        Q(pk__in=reach.machine_ids) | Q(machine_type_id__in=reach.type_ids)
    ).order_by("name")
    return {
        "machine_types": [{"id": row.pk, "name": row.name} for row in types],
        "machines": [{"id": row.pk, "name": row.name} for row in machines],
        "categories": [],
    }


def payload(makerspace, actor, *, delegated, reach=None):
    rows = list(
        rows_for(
            makerspace,
            feature=NotificationFeature.MAINTENANCE if delegated else None,
        ).order_by("feature", "event", "id")
    )
    if delegated:
        # The identity gate must match `prepare_rules` exactly, or a row is offered for
        # editing that the very next PUT refuses -- see `row_fully_reachable`.
        manageable = _manageable_identity(makerspace, actor)
        visible, hidden, projected = [], [], []
        for row in rows:
            if row_fully_reachable(row, reach, manageable_identity=manageable):
                visible.append(row)
                continue
            # A shared row the delegate owns PART of is shown redacted AND still counted as
            # a hidden policy: both halves are true at once, and reporting only one of them
            # either hides their own save or tells them nothing else applies.
            if _partially_owned_special(row, reach):
                projected.append(project_special_row(row, reach))
            hidden.append(row)
    else:
        visible, hidden, projected = rows, [], []
    marker_counts = Counter((row.feature, row.event) for row in hidden)
    roles, members = _identity_options(makerspace, actor, delegated)
    return {
        "delegated": delegated,
        "features": _features(makerspace, delegated),
        "roles": roles,
        "members": members,
        "rules": [serialize_rule(row) for row in visible] + projected,
        "managed_policy_markers": [
            {"feature": feature, "event": event, "count": count}
            for (feature, event), count in sorted(marker_counts.items())
        ],
        "scope_options": _scope_options(makerspace, reach),
    }

