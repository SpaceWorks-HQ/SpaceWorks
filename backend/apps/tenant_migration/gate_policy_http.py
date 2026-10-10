"""Explicit source-gate http participation declarations."""

from .gate_policy_replay import REPLAY_HTTP_PARTICIPANTS


HTTP_EXEMPTIONS = {
    "tenant-migration-source-quiesce": (
        "A completed export has already quiesced the source; reasserting its fenced "
        "lease must remain reachable."
    ),
    "tenant-migration-export-download-url": (
        "The encrypted archive can only be downloaded after its export quiesces the source."
    ),
    "tenant-migration-source-archive": (
        "Source cutover must archive the tenant while its gate is quiesced."
    ),
    "tenant-migration-source-recover": (
        "Verified abort recovery must reopen a migrated-out source while its gate is closed."
    ),
    "backup-recovery-state": "Deployment recovery must be able to quarantine/recover the deployment.",
    "stripe-connect-webhook": "Connect account events are platform routing state, not one source tenant.",
    "telegram-webhook": (
        "Acknowledge-and-discard: the callback route was removed when chat stopped being an "
        "action surface, so this writes nothing and cannot break quiescence. It must keep "
        "answering 200 even mid-migration, or Telegram retries an already-registered webhook "
        "for hours against a tenant that is being moved."
    ),
    "auth-login": "Global user session state is excluded from tenant quiescence.",
    "auth-mfa": "Global MFA credential state is excluded from tenant quiescence.",
    "auth-mfa-enroll": "Global MFA enrollment state is excluded from tenant quiescence.",
    "auth-mfa-confirm": "Global MFA credential and session state is excluded from tenant quiescence.",
    "auth-mfa-verify": "Global MFA verification and session state is excluded from tenant quiescence.",
    "auth-mfa-recovery": "Global MFA recovery credentials are excluded from tenant quiescence.",
    "auth-mfa-disable": "Global MFA credential state is excluded from tenant quiescence.",
    "control-mfa": "Global MFA credential and control-session state is excluded from tenant quiescence.",
    "auth-refresh": "Global user session state is excluded from tenant quiescence.",
    "auth-logout": "Global user session state is excluded from tenant quiescence.",
    "auth-change-password": "Global credential edits are excluded from tenant quiescence.",
    "auth-forgot-password": "Global account recovery is excluded from tenant quiescence.",
    "auth-reset-password": "Global credential edits are excluded from tenant quiescence.",
    "auth-member-sign-up": "Global user creation is excluded from tenant quiescence.",
    "auth-email-verification-resend": "Global user verification is excluded from tenant quiescence.",
    "auth-email-verification-confirm": "Global user verification is excluded from tenant quiescence.",
    "auth-phone-login-start": "Global phone identity state is excluded from tenant quiescence.",
    "auth-phone-login-confirm": "Global phone identity state is excluded from tenant quiescence.",
    "auth-phone-link-start": "Global phone identity state is excluded from tenant quiescence.",
    "auth-phone-link-confirm": "Global phone identity state is excluded from tenant quiescence.",
    "auth-phone-unlink": "Global phone identity state is excluded from tenant quiescence.",
    "social-nonce": "Global social identity state is excluded from tenant quiescence.",
    "social-google": "Global social identity state is excluded from tenant quiescence.",
    "social-apple": "Global social identity state is excluded from tenant quiescence.",
    "social-oidc": "Global social identity state is excluded from tenant quiescence.",
    "social-oidc-browser-start": "Global social identity state is excluded from tenant quiescence.",
    "social-oidc-browser-callback": "Global social identity state is excluded from tenant quiescence.",
    "device-attestation-challenge": "Global device authority is excluded from tenant quiescence.",
    "device-login": "Global device authority is excluded from tenant quiescence.",
    "device-refresh": "Global device authority is excluded from tenant quiescence.",
    "device-logout": "Global device authority is excluded from tenant quiescence.",
}


HTTP_ANONYMOUS_EXEMPTIONS = {
    "apps.accounts.views_device.DeviceAttestationChallengeView.post": "Global device-attestation challenge state.",
    "apps.accounts.views_device.DeviceLoginView.post": "Global user and device-session state.",
    "apps.accounts.views_device.DeviceRefreshView.post": "Global device-session state.",
    "apps.accounts.views_oidc_browser.OidcBrowserStartView.post": "Global OIDC login-attempt state.",
    "apps.accounts.views_oidc_browser.OidcBrowserCallbackView.post": "Global OIDC identity state.",
    "apps.accounts.views_password.ForgotPasswordView.post": "Global account-recovery state.",
    "apps.accounts.views_password.ResetPasswordConfirmView.post": "Global credential state.",
    "apps.accounts.views_phone.PhoneLoginStartView.post": "Global phone-login challenge state.",
    "apps.accounts.views_phone.PhoneLoginConfirmView.post": "Global phone identity and session state.",
    "apps.accounts.views_registration.MemberSignUpView.post": "Global user registration state.",
    "apps.accounts.views_login.LoginView.post": "Global user session state.",
    "apps.accounts.views_profile.LogoutView.post": "Global user session state.",
    "apps.accounts.views_mfa.MFAEnrollmentView.post": "Global MFA enrollment challenge state.",
    "apps.accounts.views_social_login.SocialNonceView.post": "Global social-login nonce state.",
    "apps.accounts.views_social_login.SocialLoginView.post": "Global social identity and session state.",
    "apps.payments_rail.views_connect.StripeConnectWebhookView.post": "Platform Connect routing state.",
    "apps.integrations.views.TelegramWebhookView.post": (
        "Writes nothing at all: the callback route was removed when chat stopped being an "
        "action surface, and the view only acknowledges so an already-registered webhook "
        "stops retrying. No tenant state is reachable from it to quiesce."
    ),
}


HTTP_ANONYMOUS_PARTICIPANTS = {
    "apps.notifications.views_preferences.OneClickUnsubscribeView.post": (
        "Signed token resolves one tenant; save_preference holds tenant_write through its audited commit."
    ),
    "apps.accounts.views_staff_invitations.StaffInvitationAcceptView.post": (
        "Token resolves one tenant; acceptance takes tenant_write before account or membership writes."
    ),
    **REPLAY_HTTP_PARTICIPANTS,
    "apps.hardware_requests.cron_views.ReturnReminderCronView.post": (
        "The fan-out reminder service takes the skip-and-count gate once per request."
    ),
    # Token-authenticated device enrollment: each view resolves the enrollment's
    # makerspace, takes the late gate for it, and the locked service re-asserts it.
    "apps.devices.views_enrollment.DeviceEnrollmentChallengeView.post": (
        "Resolves the enrollment's makerspace and asserts its source gate before mutating."
    ),
    "apps.devices.views_enrollment.DeviceEnrollmentCompleteView.post": (
        "Resolves the enrollment's makerspace and asserts its source gate before mutating."
    ),
}


ADMIN_ACTION_EXEMPTIONS = {
    "makerspaces.MakerspaceArchiveRequest.approve_selected": (
        "Approving the request performs the excluded tenant archive."
    ),
    "makerspaces.Makerspace.archive_makerspaces": (
        "Tenant archive is expressly excluded from source quiescence."
    ),
    "makerspaces.Makerspace.purge_makerspaces": (
        "Tenant purge is expressly excluded from source quiescence."
    ),
}
