"""DRF permission classes + scoping mixin + staff base view built on the rbac module."""
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.accounts import rbac
from apps.accounts.models import User

STAFF_ROLES = (User.Role.SUPERADMIN, User.Role.SPACE_MANAGER)


def _active_staff(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and user.role in STAFF_ROLES
        and user.access_status == User.AccessStatus.ACTIVE
        and not getattr(user, "must_change_password", False)
    )


class IsSuperadmin(BasePermission):
    def has_permission(self, request, view):
        u = getattr(request, "user", None)
        if not getattr(u, "is_authenticated", False):
            return False
        # re-review fix: a suspended/restricted superadmin must also be blocked.
        if u.access_status != User.AccessStatus.ACTIVE:
            return False
        # Default super123 seed must rotate before using protected endpoints.
        if getattr(u, "must_change_password", False):
            return False
        return u.is_superuser or u.role == User.Role.SUPERADMIN


class IsStaff(BasePermission):
    """Authenticated staff whose access_status is still ACTIVE.

    Re-checking access_status here — not only at login — bounds a suspended user's
    remaining access to the (short) access-token lifetime (review fix #5)."""

    def has_permission(self, request, view):
        return _active_staff(getattr(request, "user", None))


class HasMakerspaceAction(BasePermission):
    """Requires `view.required_action`; checks rbac.can within the view's makerspace.

    The view supplies the makerspace id via `get_action_makerspace_id(request)`
    (defaults to the `makerspace_id` URL kwarg)."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if getattr(user, "access_status", None) != User.AccessStatus.ACTIVE:
            return False
        if getattr(user, "must_change_password", False):
            return False
        action = getattr(view, "required_action", None)
        if action is None:
            return False
        if hasattr(view, "get_action_makerspace_id"):
            ms_id = view.get_action_makerspace_id(request)
        else:
            ms_id = view.kwargs.get("makerspace_id")
        return rbac.can(user, action, ms_id)


class MakerspaceScopedQuerysetMixin:
    """Apply makerspace scoping in get_queryset so no admin view forgets it."""

    makerspace_scope_field = "makerspace_id"

    def get_queryset(self):
        qs = super().get_queryset()
        return rbac.scope_by_makerspace(
            self.request.user, qs, self.makerspace_scope_field
        )


class StaffAPIView(MakerspaceScopedQuerysetMixin, GenericAPIView):
    """Base for ALL staff endpoints: authenticated + active staff + auto-scoped queryset.

    Future phases subclass this so the invariant 'every staff query is makerspace-scoped'
    is enforced by default rather than by remembering to add a mixin (review fix #4). Add
    `required_action` + `HasMakerspaceAction` to a subclass for per-action checks."""

    permission_classes = [IsAuthenticated, IsStaff]
