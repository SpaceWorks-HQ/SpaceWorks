"""Locked, audited mutations for per-makerspace roles."""

from django.db import transaction
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
)


class RoleConflict(Exception):
    """A role cannot be deleted (protected, or still assigned to a membership).

    Plain exception (not a DRF APIException) so the project's
    ``workflow_exception_handler`` maps it to the structured ``{detail, code}``
    body via ``_EXCEPTION_MAP`` instead of DRF's bare ``{detail}`` default."""


def _superadmin(actor):
    return actor.is_superuser or actor.role == User.Role.SUPERADMIN


def _locked_actor_actions(actor, makerspace):
    membership = (
        MakerspaceMembership.objects.select_for_update(of=("self",))
        .select_related("assigned_role")
        .filter(makerspace=makerspace, user=actor, status="active")
        .first()
    )
    if membership and membership.assigned_role_id:
        membership.assigned_role = MakerspaceRole.objects.select_for_update().get(
            pk=membership.assigned_role_id
        )
    if _superadmin(actor) and makerspace.superadmin_access_enabled:
        return set(rbac.ROLE_GRANTABLE_ACTIONS)
    return rbac.actions_for_membership(membership) | _locked_organization_actions(
        actor, makerspace
    )


def _locked_organization_actions(actor, makerspace):
    """Revalidate organization authority under locks before role mutations."""
    # Resolve candidate parent/child ids without holding either row class. The locked
    # reads below then follow Django admin's parent-first save order.
    resolved_links = list(
        OrganizationMakerspace.objects
        .filter(makerspace=makerspace)
        .values_list("organization_id", "pk")
        .order_by("pk")
    )
    organization_ids = sorted(
        {organization_id for organization_id, _ in resolved_links}
    )
    if not organization_ids:
        return set()

    # Final organization-authority lock order: Organization rows (ascending pk),
    # then OrganizationMakerspace rows (ascending pk), then OrganizationMembership
    # rows (ascending pk). Django admin takes the same parent-before-child order.
    locked_organizations = list(
        Organization.objects.select_for_update()
        .filter(pk__in=organization_ids)
        .order_by("pk")
    )
    locked_organization_ids = [
        organization.pk for organization in locked_organizations
    ]
    locked_links = list(
        OrganizationMakerspace.objects.select_for_update()
        .filter(
            pk__in=[link_id for _, link_id in resolved_links],
            organization_id__in=locked_organization_ids,
            makerspace=makerspace,
        )
        .order_by("pk")
    )
    if not locked_links:
        return set()
    locked_link_ids = [link.pk for link in locked_links]
    locked_organization_ids = sorted(
        {link.organization_id for link in locked_links}
    )
    memberships = (
        rbac._organization_authority_memberships(
            actor, makerspace_ids=[makerspace.pk]
        )
        .filter(
            organization_id__in=locked_organization_ids,
            organization__makerspace_links__pk__in=locked_link_ids,
        )
        .select_for_update(of=("self",))
        .select_related("organization")
        .order_by("pk")
    )
    actions = set()
    for membership in memberships:
        actions.update(rbac.actions_for_organization_membership(membership))
    return actions


def _clean_actions(actions):
    if not isinstance(actions, list) or any(not isinstance(item, str) for item in actions):
        raise ValidationError({"granted_actions": "Use a list of action values."})
    values = set(actions)
    if values & rbac.ROLE_FORBIDDEN_ACTIONS:
        raise ValidationError(
            {"granted_actions": "This action cannot be granted to a makerspace role."}
        )
    unknown = values - rbac.ALL_ACTIONS
    if unknown:
        raise ValidationError({"granted_actions": "Unknown action value."})
    return values


def _validate_actions(actor, makerspace, actions, role=None):
    values = _clean_actions(actions)
    is_superadmin = _superadmin(actor)
    actor_actions = _locked_actor_actions(actor, makerspace)
    if rbac.Action.MANAGE_MAKERSPACE not in actor_actions:
        raise PermissionDenied()
    if not is_superadmin:
        ceiling = actor_actions - {rbac.Action.MANAGE_MAKERSPACE}
        if not values <= ceiling:
            raise PermissionDenied()
    if role and role.legacy_role == MakerspaceMembership.Role.SPACE_MANAGER:
        if rbac.Action.MANAGE_MAKERSPACE not in values:
            raise ValidationError(
                {"granted_actions": "The Space Manager role must retain manage_makerspace."}
            )
    # No Guest Admin ceiling any more: migration 0052 retired it as a built-in, so the
    # handover role is an ordinary custom role and is bounded by the general rule above --
    # you cannot grant an action you do not hold yourself. `rbac.HANDOUT_ACTIONS` survives
    # as the definition of "handover-only" for `is_handout_only`, which decides what the
    # console shows such a staffer; it is no longer a cap on what any role may hold.
    return sorted(values)


def can_assign_role(actor, makerspace, role, target_membership=None):
    """Raise on a role assignment that would let a local manager escalate."""
    if role.makerspace_id != makerspace.id:
        raise PermissionDenied()
    actions = _clean_actions(role.granted_actions)
    actor_actions = _locked_actor_actions(actor, makerspace)
    if rbac.Action.MANAGE_MAKERSPACE not in actor_actions:
        raise PermissionDenied()
    if _superadmin(actor):
        return True
    if target_membership and rbac.Action.MANAGE_MAKERSPACE in rbac.actions_for_membership(target_membership):
        raise PermissionDenied()
    if rbac.Action.MANAGE_MAKERSPACE in actions or not actions <= (
        actor_actions - {rbac.Action.MANAGE_MAKERSPACE}
    ):
        raise PermissionDenied()
    return True


def assign_role(*, makerspace, actor, membership, role):
    """Atomically assign a makerspace role and preserve the legacy role mirror."""
    if role.makerspace_id != makerspace.id or membership.makerspace_id != makerspace.id:
        raise PermissionDenied()
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        role = MakerspaceRole.objects.select_for_update().get(
            pk=role.pk, makerspace=makerspace
        )
        membership = (
            MakerspaceMembership.objects.select_for_update(of=("self",))
            .select_related("assigned_role")
            .get(pk=membership.pk)
        )
        if membership.makerspace_id != makerspace.id:
            raise PermissionDenied()
        can_assign_role(actor, makerspace, role, target_membership=membership)
        old_role_id = membership.assigned_role_id
        old_legacy_role = membership.role
        membership.assigned_role = role
        membership.role = role.legacy_role or MakerspaceMembership.Role.CUSTOM
        membership.save(update_fields=["assigned_role", "role"])
        audit.record(
            actor,
            "staff.role_assigned",
            makerspace=makerspace,
            target=membership.user,
            meta={
                "membership_id": membership.id,
                "old_role_id": old_role_id,
                "new_role_id": role.id,
                "new_role_slug": role.slug,
            },
        )
        return membership


def _slug_for(makerspace, name, role_id=None):
    root = slugify(name)[:72] or "role"
    slug, suffix = root, 2
    query = MakerspaceRole.objects.filter(makerspace=makerspace)
    if role_id:
        query = query.exclude(pk=role_id)
    while query.filter(slug__iexact=slug).exists():
        slug = f"{root[: 80 - len(str(suffix)) - 1]}-{suffix}"
        suffix += 1
    return slug


def create_role(*, makerspace, actor, name, granted_actions):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        actions = _validate_actions(actor, makerspace, granted_actions)
        if MakerspaceRole.objects.filter(makerspace=makerspace, name__iexact=name.strip()).exists():
            raise ValidationError({"name": "A role with this name already exists."})
        limits.check_quota(makerspace, "custom_roles", adding=1)
        role = MakerspaceRole.objects.create(
            makerspace=makerspace, name=name, slug=_slug_for(makerspace, name), granted_actions=actions
        )
        audit.record(actor, "role.created", makerspace=makerspace, target=role,
                     meta={"id": role.id, "name": role.name, "slug": role.slug})
        return role


def update_role(*, makerspace, role, actor, name=None, granted_actions=None):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        role = MakerspaceRole.objects.select_for_update().get(pk=role.pk, makerspace=makerspace)
        # A rename still requires management but intentionally does not revalidate grants.
        actor_actions = _locked_actor_actions(actor, makerspace)
        if rbac.Action.MANAGE_MAKERSPACE not in actor_actions:
            raise PermissionDenied()
        changes, old_actions = [], set(role.granted_actions)
        if name is not None and name.strip() != role.name:
            if MakerspaceRole.objects.filter(makerspace=makerspace, name__iexact=name.strip()).exclude(pk=role.pk).exists():
                raise ValidationError({"name": "A role with this name already exists."})
            role.name, role.slug = name, _slug_for(makerspace, name, role.pk)
            changes.append("name")
        if granted_actions is not None:
            role.granted_actions = _validate_actions(actor, makerspace, granted_actions, role)
            if set(role.granted_actions) != old_actions:
                changes.append("granted_actions")
        if changes:
            role.save()
            audit.record(actor, "role.updated", makerspace=makerspace, target=role, meta={
                "changed_fields": changes,
                "added_actions": sorted(set(role.granted_actions) - old_actions),
                "removed_actions": sorted(old_actions - set(role.granted_actions)),
            })
        return role


def delete_role(*, makerspace, role, actor):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        role = MakerspaceRole.objects.select_for_update().get(pk=role.pk, makerspace=makerspace)
        actor_actions = _locked_actor_actions(actor, makerspace)
        if rbac.Action.MANAGE_MAKERSPACE not in actor_actions:
            raise PermissionDenied()
        if role.is_protected or MakerspaceMembership.objects.filter(assigned_role=role).exists():
            raise RoleConflict()
        meta = {"id": role.id, "name": role.name, "slug": role.slug}
        role.delete()
        audit.record(actor, "role.deleted", makerspace=makerspace, target_type="makerspaces.makerspacerole", meta=meta)
