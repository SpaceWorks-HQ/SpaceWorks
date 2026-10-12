"""Audited creation, editing and deletion of tenant roles."""
from django.db import transaction
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.role_authority import RoleConflict, _locked_actor_actions, _validate_actions


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
            role.name = name
            # A protected default is found by its slug (`member` by every activation path,
            # tenant migration and `ensure_default_roles`), so renaming one relabels it and
            # never re-slugs it -- re-slugging would break every join at once.
            if not role.is_protected:
                role.slug = _slug_for(makerspace, name, role.pk)
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
