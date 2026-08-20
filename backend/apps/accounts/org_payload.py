"""Batched projection of organization authority into the auth payload."""

import logging

from apps.accounts import rbac
from apps.accounts.models import User


def membership_makerspace_entry(
    membership,
    *,
    actions,
    can_configure_machine_types,
    is_machine_only,
):
    """Serialize one real membership while preserving its identity semantics."""
    assigned_role = membership.assigned_role
    role_name = (
        assigned_role.name
        if membership.assigned_role_id is not None
        else _legacy_role_name(membership.role)
    )
    role_slug = (
        assigned_role.slug
        if membership.assigned_role_id is not None
        else membership.role
    )
    return {
        "id": membership.makerspace_id,
        "slug": membership.makerspace.slug,
        "role": membership.role,
        "role_id": membership.assigned_role_id,
        "role_name": role_name,
        "role_slug": role_slug,
        "actions": actions,
        "can_configure_machine_types": can_configure_machine_types,
        "is_machine_only": is_machine_only,
        "can_refer": membership.can_refer,
        "can_verify": membership.can_verify,
        "verified_at": membership.verified_at,
        "referrals_enabled": membership.makerspace.referrals_enabled,
        "source": "membership",
    }


def _legacy_role_name(role):
    from apps.makerspaces.models import MakerspaceMembership

    try:
        return MakerspaceMembership.Role(role).label
    except ValueError:
        return role.replace("_", " ").title()


def organization_makerspace_entries(user, *, makerspace_ids=None):
    """Return one payload entry per makerspace reached by organization grants.

    The join is intentionally one query regardless of the number of organizations
    or linked makerspaces. Callers merge these rows with already-loaded local
    memberships, avoiding an ``effective_actions`` query per makerspace.
    """
    if user.is_superuser or user.role == User.Role.SUPERADMIN:
        return {}
    rows = (
        rbac._organization_authority_memberships(
            user,
            makerspace_ids=makerspace_ids,
        )
        .values_list(
            "organization_id",
            "organization__name",
            "granted_actions",
            "organization__makerspace_links__makerspace_id",
            "organization__makerspace_links__makerspace__slug",
            "organization__makerspace_links__makerspace__referrals_enabled",
        )
        .order_by(
            "organization__name",
            "organization_id",
            "organization__makerspace_links__makerspace_id",
        )
    )
    entries = {}
    for _organization_id, name, value, space_id, slug, referrals_enabled in rows:
        if not isinstance(value, list):
            logging.getLogger(__name__).warning(
                "Ignoring malformed granted actions on an organization membership."
            )
            continue
        actions = rbac.expand_implied_actions({
            action
            for action in value
            if (
                isinstance(action, str)
                and action in rbac.ORGANIZATION_GRANTABLE_ACTIONS
            )
        })
        if not actions:
            continue
        entry = entries.setdefault(
            space_id,
            {
                "id": space_id,
                "slug": slug,
                "role": None,
                "role_id": None,
                "role_name": name,
                "role_slug": None,
                "actions": set(),
                "can_configure_machine_types": False,
                "is_machine_only": False,
                "can_refer": False,
                "can_verify": False,
                "verified_at": None,
                "referrals_enabled": referrals_enabled,
                "source": "organization",
            },
        )
        entry["actions"].update(actions)

    for entry in entries.values():
        entry["actions"] = sorted(entry["actions"])
    return entries
