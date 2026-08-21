from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.origin_scope import (
    object_in_staff_origin_scope,
    staff_origin_scope_allows,
)


def active_user(user):
    # `must_change_password` (the default super123 seed) must NOT be able to reach
    # protected staff/admin endpoints over the API before rotating — only the
    # IsAuthenticated rotation path (/auth/change-password, /auth/me) stays open.
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.access_status == User.AccessStatus.ACTIVE
        and not getattr(user, "must_change_password", False)
    )


class IsActiveStaff(BasePermission):
    def has_permission(self, request, view):
        return active_user(getattr(request, "user", None)) and staff_origin_scope_allows(
            request,
            view,
        )

    def has_object_permission(self, request, view, obj):
        return object_in_staff_origin_scope(request, obj)


class IsActiveSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return active_user(user) and (
            user.is_superuser or user.role == User.Role.SUPERADMIN
        ) and staff_origin_scope_allows(request, view)

    def has_object_permission(self, request, view, obj):
        return object_in_staff_origin_scope(request, obj)


def require_action(user, action, makerspace_id):
    if not rbac.can(user, action, makerspace_id):
        raise PermissionDenied()


def require_user_access_mutation(actor, target):
    hidden_memberships = target.makerspace_memberships.filter(
        makerspace__superadmin_access_enabled=False,
    ).values_list("makerspace_id", flat=True)
    for makerspace_id in hidden_memberships:
        if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace_id):
            raise PermissionDenied(
                "This user belongs to a makerspace that turned off superadmin access."
            )


def require_makerspace_superadmin_access(actor, makerspace):
    if (
        not makerspace.superadmin_access_enabled
        and not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk)
    ):
        raise PermissionDenied("This makerspace turned off superadmin access.")


def hidden_space_manager_reset_break_glass(target):
    memberships = list(target.makerspace_memberships.select_related("makerspace"))
    hidden = [
        membership
        for membership in memberships
        if not membership.makerspace.superadmin_access_enabled
    ]
    if not hidden:
        return False
    allowed = len(hidden) == len(memberships) and all(
        rbac.can(target, rbac.Action.MANAGE_MAKERSPACE, membership.makerspace_id)
        for membership in memberships
    )
    if not allowed:
        raise PermissionDenied(
            "Cannot reset a user who belongs to a makerspace that turned off superadmin access."
        )
    return True
