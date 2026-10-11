"""Atomic first-run configuration; outbound invitation delivery follows commit."""
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.accounts.services_staff_invitations import create as create_invitation
from apps.accounts.staff_invitation_delivery import deliver
from apps.audit import services as audit
from apps.makerspaces.models import MakerspaceRole
from apps.makerspaces.module_install import ModuleInstallError, replace_modules
from apps.makerspaces.module_registry import core_module_keys, with_dependencies
from apps.makerspaces.roles import ensure_default_roles


def configure_creation(actor, space, setup):
    # Called within MakerspaceMutationMixin.create's transaction. Never let a
    # standalone caller leave a half-created profile or authority grant behind.
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Creation setup requires the creation transaction.")
    if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, space.pk):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied()
    if "modules" in setup:
        try:
            replace_modules(space, with_dependencies(core_module_keys() | set(setup["modules"])), actor)
        except ModuleInstallError as exc:
            raise ValidationError({"creation_setup": {"modules": str(exc)}}) from exc
    profile = setup.get("profile", {})
    changed = []
    for field in ("timezone", "country", "opening_hours"):
        if field in profile and getattr(space, field) != profile[field]:
            setattr(space, field, profile[field])
            changed.append(field)
    if changed:
        space.save(update_fields=[*changed, "updated_at"])
    if "default_currency" in profile:
        from apps.payments.models import MakerspacePaymentSettings
        row, _ = MakerspacePaymentSettings.objects.get_or_create(makerspace=space)
        if row.default_currency != profile["default_currency"]:
            row.default_currency = profile["default_currency"]
            row.save(update_fields=["default_currency"])
            changed.append("default_currency")
    if changed:
        audit.record(actor, "makerspace.profile_updated", makerspace=space, target=space,
                     meta={"fields": sorted(changed)})
    invite = setup.get("first_staff_invite")
    if invite:
        ensure_default_roles(space)
        role = rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE,
                                   MakerspaceRole.objects.filter(makerspace=space)).get(slug=invite["role_slug"])
        row, raw = create_invitation(actor, space.pk, email=invite["email"], role_id=role.pk)
        # Delivery fails safely and returns a privately shareable fallback link.
        transaction.on_commit(lambda: setattr(space, "creation_invitation", deliver(row, raw)))
