"""Explicit source-gate exemptions for platform-global and recovery entry points."""


# These URL names either mutate no tenant-owned state, or are the recovery/import
# control plane that must remain operable while a source tenant is frozen.
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
    "auth-login": "Global user session state is excluded from tenant quiescence.",
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


# Anonymous/AllowAny mutating views that are deployment-global rather than tenant
# writers. Exact class-method targets are stale-checked by the HTTP AST guard.
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
    "apps.accounts.views_session.LoginView.post": "Global user session state.",
    "apps.accounts.views_session.LogoutView.post": "Global user session state.",
    "apps.accounts.views_social.SocialNonceView.post": "Global social-login nonce state.",
    "apps.accounts.views_social.SocialLoginView.post": "Global social identity and session state.",
    "apps.payments.views_connect.StripeConnectWebhookView.post": "Platform Connect routing state.",
}


HTTP_ANONYMOUS_PARTICIPANTS = {
    "apps.hardware_requests.cron_views.ReturnReminderCronView.post": (
        "The fan-out reminder service takes the skip-and-count gate once per request."
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


# Task names are exact Celery registry names. Exemptions are intentionally narrow and
# checked by the AST coverage test so deleted tasks leave stale entries behind.
TASK_EXEMPTIONS = {
    "apps.accounts.tasks.purge_auth_challenges_task": "Platform-global auth retention.",
    "apps.accounts.tasks.drain_password_reset_envelopes_task": "Platform-global account recovery.",
    "apps.audit.tasks.run_audit_attestation_task": (
        "Deployment-local audit attestation: batches and leaves are deployment "
        "state (OMITTED_MODELS), not tenant domain data, and sealing appends only "
        "to that state."
    ),
    "apps.backup.tasks.run_backup_archive_task": "Deployment/tenant backup control plane.",
    "apps.backup.tasks.scheduled_deployment_backup_task": "Deployment backup control plane.",
    "apps.backup.tasks.purge_expired_backup_archives_task": "Platform backup retention.",
    "apps.backup.tasks.cleanup_expired_restore_rollbacks_task": "Deployment recovery cleanup.",
    "apps.tenant_migration.tasks.cleanup_expired_import_jobs_task": "Target-side import retention and recovery.",
    "apps.tenant_migration.tasks.cleanup_abandoned_import_objects_task": "Target-side import object rollback does not mutate the frozen source.",
    "apps.tenant_migration.tasks.resume_expired_finalizing_import_jobs_task": "Target-side import finalization recovery does not mutate the frozen source.",
    "apps.tenant_migration.tasks.run_import_job_task": "Target-side tenant materialization does not mutate the frozen source.",
}


# Exact task-to-row resolution for single-tenant jobs. The task base reads only the
# tenant FK first, then takes the tenant lock and performs the whole task under it.
TASK_TENANT_RESOLVERS = {
    "apps.admin_api.tasks.process_bulk_import_job": (
        "admin_api.BulkImportJob", 0, "makerspace_id"
    ),
    "apps.data_export.tasks.run_data_export_task": (
        "data_export.DataExportJob", 0, "makerspace_id"
    ),
    "apps.integrations.tasks.deliver_email_task": (
        "integrations.EmailLog", 0, "makerspace_id"
    ),
    "apps.integrations.tasks.deliver_notification_task": (
        "integrations.NotificationDeliveryLog", 0, "makerspace_id"
    ),
}


# Fan-out tasks must take one tenant lock per item; holding an unscoped lock for a
# whole scan would let an unrelated tenant delay quiescence.
TASK_INTERNAL_PARTICIPANTS = {
    "apps.tenant_migration.tasks.run_migration_export_job_task": (
        "The source export claims and holds source_archive_write for its full lifecycle."
    ),
    "apps.data_export.tasks.purge_expired_exports_task": (
        "Each expired export uses the skip-and-count tenant boundary."
    ),
    "apps.hardware_requests.tasks.send_return_reminders_task": (
        "Each reminder lifecycle uses the skip-and-count tenant boundary."
    ),
    "apps.makerspaces.tasks.refresh_github_contributions_task": (
        "Each profile refresh uses the skip-and-count tenant boundary."
    ),
}


# Exact function owners for deployment-wide scans that resolve and gate one tenant at
# a time. The AST guard requires every owner to use the shared skip-and-count boundary.
FANOUT_GATE_PARTICIPANTS = {
    "apps.data_export.tasks.purge_expired_exports_task": "Expired export cleanup.",
    "apps.hardware_requests.services_return_reminders.run_return_reminders": (
        "Overdue loan reminders."
    ),
    "apps.makerspaces.tasks.refresh_github_contributions_task": "GitHub profile refresh.",
}


LIFECYCLE_EXEMPTIONS = {
    "apps.encryption.services.rotate_dek": "DEK rotation is expressly excluded from source quiescence.",
    "apps.encryption.services.disable_dek": "DEK lifecycle is expressly excluded from source quiescence.",
    "apps.encryption.services.rewrap_dek": "DEK rotation is expressly excluded from source quiescence.",
    "apps.makerspaces.lifecycle.purge": "Tenant purge is expressly excluded from source quiescence.",
    "apps.makerspaces.lifecycle.archive": "Tenant archive is expressly excluded from source quiescence.",
    "apps.makerspaces.lifecycle._archive_locked": "Cutover's locked tenant archive is expressly excluded.",
}


# Non-view object mutations whose caller supplies the request/task session gate or a
# service-owned transaction gate. These are participation declarations, not bypasses;
# the AST guard rejects stale targets.
OBJECT_MUTATION_PARTICIPANTS = {
    "apps.data_export.services._fail_job": "Called only by the task-resolved run_export_job lifecycle.",
    "apps.data_export.services._finalize_job": "Called only by the task-resolved run_export_job lifecycle.",
    "apps.events.services_images.remove_image": "Called by the tenant-resolved event image route.",
    "apps.events.services_images.update_image": "Called by the tenant-resolved event image route.",
    "apps.hardware_requests.direct_loan_returns.validate_evidence_upload": "Runs inside the guarded direct-loan return transaction.",
    "apps.hardware_requests.handover_workflow.issue_request": "Runs inside the request route's tenant transaction.",
    "apps.hardware_requests.return_workflow.return_items": "Runs inside the request route's tenant transaction.",
    "apps.machines.public_printer_service.submit_request": "Runs inside the public-slug printer request route.",
    "apps.machines.services.attach_document": "Runs inside the model-resolved machine document route.",
    "apps.machines.services.remove_document": "Runs inside the model-resolved machine document route.",
    "apps.machines.services.remove_image": "Runs inside the model-resolved machine image route.",
    "apps.machines.services.update_image": "Runs inside the model-resolved machine image route.",
    "apps.maintenance.services_documents.delete_log_document": "Runs inside the model-resolved maintenance document route.",
    "apps.maintenance.services_documents.finalize_log_document": "Runs inside the model-resolved maintenance document route.",
    "apps.makerspaces.lifecycle._delete_public_image_keys": "Tenant purge is an express source-gate exclusion.",
    "apps.makerspaces.profile_images._swap": "Runs inside the authenticated member profile image route.",
}
