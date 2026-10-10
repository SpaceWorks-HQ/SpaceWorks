from django.urls import path

from apps.accounts.views_mfa import (
    MFAConfirmView, MFADisableView, MFAEnrollmentView, MFARecoveryView, MFAStatusView, MFAVerifyView,
)
from apps.accounts.views_staff_invitations import (
    StaffInvitationAcceptView, StaffInvitationListView, StaffInvitationResendView, StaffInvitationRevokeView,
)

auth_urlpatterns = [
    path("mfa", MFAStatusView.as_view(), name="auth-mfa"),
    path("mfa/enroll", MFAEnrollmentView.as_view(), name="auth-mfa-enroll"),
    path("mfa/confirm", MFAConfirmView.as_view(), name="auth-mfa-confirm"),
    path("mfa/verify", MFAVerifyView.as_view(), name="auth-mfa-verify"),
    path("mfa/recovery", MFARecoveryView.as_view(), name="auth-mfa-recovery"),
    path("mfa/disable", MFADisableView.as_view(), name="auth-mfa-disable"),
    path("staff-invitations/accept", StaffInvitationAcceptView.as_view(), name="auth-staff-invitation-accept"),
]

admin_urlpatterns = [
    path("makerspaces/<int:makerspace_id>/staff-invitations", StaffInvitationListView.as_view(), name="admin-staff-invitations"),
    path("makerspaces/<int:makerspace_id>/staff-invitations/<int:invitation_id>/revoke", StaffInvitationRevokeView.as_view(), name="admin-staff-invitation-revoke"),
    path("makerspaces/<int:makerspace_id>/staff-invitations/<int:invitation_id>/resend", StaffInvitationResendView.as_view(), name="admin-staff-invitation-resend"),
]
