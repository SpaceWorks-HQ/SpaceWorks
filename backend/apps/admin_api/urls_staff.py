from django.urls import path

from apps.admin_api import views
from apps.makerspaces.models import MakerspaceMembership


urlpatterns = [
    path(
        "users/space-managers",
        views.StaffListCreateView.as_view(),
        {"role": MakerspaceMembership.Role.SPACE_MANAGER},
        name="admin-users-space-managers",
    ),
    path(
        "users/inventory-managers",
        views.StaffListCreateView.as_view(),
        {"role": MakerspaceMembership.Role.INVENTORY_MANAGER},
        name="admin-users-inventory-managers",
    ),
    # `users/guest-admins` is gone: Guest Admin is no longer a built-in role, so there is
    # no fixed role for this route to create. Handover staff are given a custom role
    # through the role-assignment API, which is what the console has used all along --
    # nothing in the frontend or the test suite ever called this endpoint.
    # `users/print-managers` is gone for the same reason as `users/guest-admins`, and it
    # was worse than dead: migration 0046 retired Print Manager into Machine Manager but
    # left the route mounted, so on any makerspace created since -- which never seeds a
    # print_manager role -- a POST here raised MakerspaceRole.DoesNotExist and 500'd.
    # Machine Manager is the role it became; `users/machine-managers` is the way in.
    path(
        "users/machine-managers",
        views.StaffListCreateView.as_view(),
        {"role": MakerspaceMembership.Role.MACHINE_MANAGER},
        name="admin-users-machine-managers",
    ),
    path(
        "memberships/<int:pk>",
        views.MembershipRevokeView.as_view(),
        name="admin-membership-revoke",
    ),
    path("users/<int:pk>/restrict", views.RestrictUserView.as_view(), name="user-restrict"),
    path(
        "users/<int:pk>/reset-password",
        views.ResetUserPasswordView.as_view(),
        name="admin-user-reset-password",
    ),
    path(
        "users/<int:pk>/restore-access",
        views.RestoreUserAccessView.as_view(),
        name="user-restore-access",
    ),
    path("audit-logs", views.AuditLogListView.as_view(), name="admin-audit-logs"),
]
