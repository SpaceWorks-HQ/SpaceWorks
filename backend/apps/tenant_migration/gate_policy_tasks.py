"""Explicit source-gate tasks participation declarations."""

from .gate_policy_replay import REPLAY_TASK_PARTICIPANTS, REPLAY_FANOUT_PARTICIPANTS


TASK_EXEMPTIONS = {
    "apps.operations.tasks_platform.run_platform_problem_checks_task": (
        "Read-only platform monitoring; writes only a disposable deployment cache marker."
    ),
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
    "apps.backup.tasks.deliver_archive_custody_alarms_task": (
        "Archive-custody alarm delivery. Writes only its own outbox rows and the "
        "derived custody-state delivery marker -- both deployment control-plane "
        "state, never tenant domain data -- and sends mail. It reads a makerspace "
        "to resolve recipients but mutates no tenant row, so it cannot disturb a "
        "frozen source."
    ),
    "apps.backup.tasks.deliver_tenant_exit_custody_alarms_task": (
        "Lane D custody-alarm delivery writes only deployment-local derived state "
        "and its recoverable outbox before sending mail."
    ),
    "apps.backup.tasks_offsite.push_offsite_backups_task": (
        "Deployment offsite copy control plane: pushes, prunes and re-verifies sealed archives."
    ),
    "apps.backup.tasks_offsite.rehydrate_backup_archive_task": (
        "Deployment recovery: rehydrates a sealed archive from an offsite destination."
    ),
    "apps.backup.tasks.reconcile_backup_artifacts_task": (
        "Deployment-local backup staging, verification, and artifact ledger recovery."
    ),
    "apps.tenant_migration.tasks.cleanup_expired_import_jobs_task": "Target-side import retention and recovery.",
    "apps.tenant_migration.tasks.cleanup_abandoned_import_objects_task": "Target-side import object rollback does not mutate the frozen source.",
    "apps.tenant_migration.tasks.cleanup_refused_tenant_dump_artifacts_task": (
        "Lane D unpublished-byte cleanup mutates only source-deployment coordination state."
    ),
    "apps.tenant_migration.tasks.resume_expired_finalizing_import_jobs_task": "Target-side import finalization recovery does not mutate the frozen source.",
    "apps.tenant_migration.tasks.run_import_job_task": "Target-side tenant materialization does not mutate the frozen source.",
}


TASK_TENANT_RESOLVERS = {
    "apps.data_export.subject_tasks.run_subject_export_task": (
        "data_export.DataExportJob", 0, "makerspace_id"
    ),
    "apps.admin_api.tasks.process_bulk_import_job": (
        "admin_api.BulkImportJob", 0, "makerspace_id"
    ),
    "apps.audit.tasks.run_audit_verification": (
        "audit.AuditVerificationRun", 0, "makerspace_id"
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


TASK_INTERNAL_PARTICIPANTS = {
    "apps.data_export.subject_tasks.sweep_subject_exports_task": (
        "Queued personal exports use separate skip-and-count tenant boundaries."
    ),
    "apps.operations.tasks_admissions.sweep_membership_admissions_task": (
        "Admission expiry and committed-settlement recovery gate each tenant before writes."
    ),
    "apps.operations.tasks_reminders.run_reminder_sweep_task": (
        "Reminder discovery, claims and dispatch use one skip-and-count tenant boundary."
    ),
    **REPLAY_TASK_PARTICIPANTS,
    "apps.devices.tasks.scan_offline_devices_task": "Offline/retention service gates each tenant separately.",
    "apps.tenant_migration.tasks.run_migration_export_job_task": (
        "The source export claims and holds source_archive_write for its full lifecycle."
    ),
    "apps.evidence.tasks.cleanup_abandoned_evidence_uploads_task": (
        "New cleanup uses the skip-and-count tenant boundary; receipt reconciliation is "
        "declared deployment coordination."
    ),
    "apps.data_export.tasks.purge_expired_exports_task": (
        "Each expired export uses the skip-and-count tenant boundary."
    ),
    "apps.hardware_requests.tasks.send_return_reminders_task": (
        "Each reminder lifecycle uses the skip-and-count tenant boundary."
    ),
    "apps.evidence.tasks.sweep_evidence_retention_task": (
        "Each evidence expiry uses the skip-and-count tenant boundary."
    ),
    "apps.events.tasks.extend_event_series_task": (
        "Each series extension locks its own makerspace and uses the skip-and-count "
        "tenant boundary; the queryset is servable-filtered before iteration."
    ),
    "apps.operations.tasks.finalize_report_rollups_task": (
        "Each rollup finalisation uses the skip-and-count tenant boundary; the "
        "makerspace queryset is servable-filtered before iteration."
    ),
    "apps.operations.tasks_report_schedules.run_report_schedules_task": (
        "Each due schedule runs inside its own skip-and-count tenant boundary; the "
        "due queryset is filtered to report-eligible (servable) makerspaces first."
    ),
    "apps.makerspaces.tasks.refresh_github_contributions_task": (
        "Each profile refresh uses the skip-and-count tenant boundary."
    ),
    "apps.makerspaces.tasks_membership.run_membership_renewals_task": (
        "Each term expiry and renewal charge uses the skip-and-count tenant boundary."
    ),
    "apps.apiclients.tasks.flush_api_client_usage_task": (
        "Writes only deployment-local last-seen telemetry on ApiClient rows; it moves no "
        "tenant data and so needs no per-tenant gate."
    ),
    "apps.makerspaces.tasks_station.purge_expired_operator_leases_task": (
        "Each tenant's expired kiosk leases use the skip-and-count tenant boundary."
    ),
}


FANOUT_GATE_PARTICIPANTS = {
    "apps.data_export.subject_tasks.sweep_subject_exports_task": "Personal export recovery gates each tenant.",
    "apps.makerspaces.membership_admission_payments.sweep_admissions": (
        "Admission expiry and settlement retries use separate skip-and-count tenant boundaries."
    ),
    "apps.notifications.retention.run_notification_retention": (
        "Bounded inbox and terminal delivery cleanup gates each tenant separately."
    ),
    "apps.operations.reminder_sweeper.run_reminder_sweep": (
        "Shared source-local reminders; each tenant is gated before discovery or dispatch."
    ),
    **REPLAY_FANOUT_PARTICIPANTS,
    "apps.devices.services_offline.scan_offline_devices": "Device offline edges and auth-artifact retention.",
    "apps.data_export.tasks.purge_expired_exports_task": "Expired export cleanup.",
    "apps.evidence.abandoned_upload_cleanup.sweep_abandoned_evidence_uploads": (
        "Abandoned evidence-upload cleanup."
    ),
    "apps.evidence.services_retention.sweep_evidence_retention": (
        "Evidence object expiry."
    ),
    "apps.hardware_requests.services_return_reminders._run_legacy_return_reminders": (
        "Overdue loan reminders."
    ),
    "apps.makerspaces.tasks.refresh_github_contributions_task": "GitHub profile refresh.",
    "apps.makerspaces.membership_renewals.run_membership_renewals": (
        "Membership term expiry and renewal charges."
    ),
    "apps.operations.report_schedule_services.run_report_schedules": "Due scheduled report deliveries.",
    "apps.makerspaces.station_lease_cleanup.purge_expired_operator_leases": (
        "Expired kiosk operator lease cleanup."
    ),
}
