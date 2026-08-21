"""Visibility rules for tenant import targets."""

from apps.accounts import rbac
from apps.accounts.models import User
from apps.accounts.rbac_superadmin import (
    superadmin_hidden_to_exclude_without_servability,
)


def scope_import_target_makerspaces(actor, queryset):
    """Scope a superadmin's targets without applying normal servability."""
    is_superadmin = bool(
        actor is not None
        and getattr(actor, "is_authenticated", False)
        and (actor.is_superuser or actor.role == User.Role.SUPERADMIN)
    )
    if not is_superadmin:
        return queryset.none()

    # Import targets legitimately remain non-servable until cutover. Apply the
    # hard-hide policy here, but not normal tenant servability.
    excluded = superadmin_hidden_to_exclude_without_servability(
        actor, rbac.Action.MANAGE_MAKERSPACE
    )
    return queryset.exclude(pk__in=excluded)
