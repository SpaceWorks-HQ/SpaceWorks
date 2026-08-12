"""Actor-aware visibility and payload construction for recipient-rule administration."""

from collections import Counter

from django.db.models import Q

from apps.admin_api.recipient_rule_common import (
    memberships_for,
    row_fully_reachable,
    rows_for,
)
from apps.integrations import notification_catalog, recipients as recipient_selection
from apps.integrations.notification_enums import NotificationFeature
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
        visible = [row for row in rows if row_fully_reachable(row, reach)]
        hidden = [row for row in rows if not row_fully_reachable(row, reach)]
    else:
        visible, hidden = rows, []
    marker_counts = Counter((row.feature, row.event) for row in hidden)
    roles, members = _identity_options(makerspace, actor, delegated)
    return {
        "delegated": delegated,
        "features": _features(makerspace, delegated),
        "roles": roles,
        "members": members,
        "rules": [serialize_rule(row) for row in visible],
        "managed_policy_markers": [
            {"feature": feature, "event": event, "count": count}
            for (feature, event), count in sorted(marker_counts.items())
        ],
        "scope_options": _scope_options(makerspace, reach),
    }

