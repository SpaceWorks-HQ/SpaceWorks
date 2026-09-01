from django.urls import path

from apps.admin_api.views_member_capabilities import (
    AdminMembershipCapabilitiesView,
    AdminMembershipUnverifyView,
    AdminMembershipVerifyView,
)
from apps.admin_api.views_member_claim import (
    MemberClaimCodeListCreateView,
    MemberClaimCodeRevokeView,
)
from apps.admin_api.views_member_memberships import (
    AdminInvitationView,
    AdminMembershipRequestListView,
    AdminMembershipRevokeM2View,
    AdminMembershipRoleM2View,
    AdminMembershipRosterView,
    AdminRequestApproveView,
    AdminRequestRevokeView,
    AdminWaiverView,
)
from apps.admin_api.views_memberships import (
    MembershipListCreateView,
    MembershipRoleAssignView,
)
from apps.admin_api.views_roles import (
    CapabilityCatalogView,
    RoleDetailView,
    RoleListCreateView,
    RoleMachineScopeView,
)
from apps.admin_api.views_walk_in import WalkInMemberCreateView
from apps.admin_api.views_waiver_witness import AdminWitnessWaiverAcceptanceView


roster_urlpatterns = [
    path("memberships", AdminMembershipRosterView.as_view(), name="admin-memberships-roster"),
    path("membership-requests", AdminMembershipRequestListView.as_view(), name="admin-membership-requests"),
    path("makerspace/<int:makerspace_id>/membership-invitations", AdminInvitationView.as_view(), name="admin-membership-invitations"),
    path("membership-requests/<int:pk>/approve", AdminRequestApproveView.as_view(), name="admin-membership-request-approve"),
    path("membership-requests/<int:pk>/revoke", AdminRequestRevokeView.as_view(), name="admin-membership-request-revoke"),
    path("memberships/<int:pk>/revoke", AdminMembershipRevokeM2View.as_view(), name="admin-membership-revoke-m2"),
    path("memberships/<int:pk>/role", AdminMembershipRoleM2View.as_view(), name="admin-membership-role-m2"),
    path("memberships/<int:pk>/capabilities", AdminMembershipCapabilitiesView.as_view(), name="admin-membership-capabilities"),
    path("memberships/<int:pk>/verify", AdminMembershipVerifyView.as_view(), name="admin-membership-verify"),
    path("memberships/<int:pk>/unverify", AdminMembershipUnverifyView.as_view(), name="admin-membership-unverify"),
    path("memberships/<int:pk>/waiver/witness", AdminWitnessWaiverAcceptanceView.as_view(), name="admin-membership-waiver-witness"),
    path("makerspaces/<int:makerspace_id>/waiver", AdminWaiverView.as_view(), name="admin-makerspace-waiver"),
]


management_urlpatterns = [
    path(
        "makerspaces/<int:makerspace_id>/memberships",
        MembershipListCreateView.as_view(),
        name="admin-membership-list-create",
    ),
    path(
        "makerspaces/<int:makerspace_id>/walk-in-members",
        WalkInMemberCreateView.as_view(),
        name="admin-walk-in-member-create",
    ),
    path(
        "makerspaces/<int:makerspace_id>/member-claim-codes",
        MemberClaimCodeListCreateView.as_view(),
        name="admin-member-claim-code-list-create",
    ),
    path(
        "makerspaces/<int:makerspace_id>/member-claim-codes/<int:claim_id>/revoke",
        MemberClaimCodeRevokeView.as_view(),
        name="admin-member-claim-code-revoke",
    ),
    path(
        "makerspaces/<int:makerspace_id>/memberships/<int:membership_id>/role",
        MembershipRoleAssignView.as_view(),
        name="admin-membership-role-assign",
    ),
    path(
        "makerspaces/<int:makerspace_id>/roles/capabilities",
        CapabilityCatalogView.as_view(),
        name="admin-role-capabilities",
    ),
    path(
        "makerspaces/<int:makerspace_id>/roles",
        RoleListCreateView.as_view(),
        name="admin-role-list-create",
    ),
    path(
        "makerspaces/<int:makerspace_id>/roles/<int:role_id>",
        RoleDetailView.as_view(),
        name="admin-role-detail",
    ),
    path(
        "makerspaces/<int:makerspace_id>/roles/<int:role_id>/machine-scope",
        RoleMachineScopeView.as_view(),
        name="admin-role-machine-scope",
    ),
]
