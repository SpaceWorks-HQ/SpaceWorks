"""Object-storage writers whose caller holds the tenant source-gate boundary.

Explicitly re-exported from gate_policy; this split keeps new replay policy from
pushing the shared policy file against its production-code ceiling.
"""



# Non-view object mutations whose caller supplies the request/task session gate or a
# service-owned transaction gate. These are participation declarations, not bypasses;
# the AST guard rejects stale targets.
OBJECT_MUTATION_PARTICIPANTS = {
    "apps.hardware_requests.replay_execute.execute": "Replay Station boundary spans external finalization; live checks assert the gate in both transactions.",
    "apps.hardware_requests.replay_prepare._upload_again": "Called inside replay prepare's Station-resolved source-gate boundary.",
    "apps.data_export.services._fail_job": "Called only by the task-resolved run_export_job lifecycle.",
    "apps.data_export.services._finalize_job": "Called only by the task-resolved run_export_job lifecycle.",
    "apps.data_export.services.run_export_job": (
        "The export task resolves and holds the tenant gate for this lifecycle."
    ),
    "apps.evidence.services_upload.issue_upload": (
        "Called only by the staff upload-URL and kiosk evidence-prepare views, both behind "
        "the authenticated late source-gate assertion; the kiosk view also asserts it."
    ),
    "apps.evidence.finalization.finalize_upload": "Reached only through the already-declared handover, return and direct-loan entry points.",
    "apps.evidence.services_retention._sweep_makerspace": (
        "The fan-out service owns one tenant source-gate boundary at a time."
    ),
    "apps.events.services_images.remove_image": "Called by the tenant-resolved event image route.",
    "apps.makerspaces.member_card_storage.presign_photo": "Called only by the tenant-resolved member-card photo route.",
    "apps.makerspaces.member_card_storage.finalize_photo": "Called only by the tenant-resolved member-card photo route.",
    "apps.makerspaces.member_card_storage._release": "Reached only through the member-card photo route, revoke and the membership purge.",
    "apps.events.services_images.update_image": "Called by the tenant-resolved event image route.",
    "apps.events.services_series_images.remove_image": "Called by the tenant-resolved event series image route.",
    "apps.events.services_series_images.update_image": "Called by the tenant-resolved event series image route.",
    "apps.events.services.update_event": (
        "Runs inside the tenant-resolved admin event route's transaction; it can clear "
        "image_key when an occurrence stops overriding its series template."
    ),
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
    "apps.makerspaces.lifecycle_storage._delete_public_image_keys": "Tenant purge is an express source-gate exclusion.",
    "apps.operations.report_delivery_storage.delete_report_object": (
        "Reached only inside run_report_schedules' skip-and-count tenant boundary, the "
        "tenant-resolved schedule delete route and the reports module purge."
    ),
    "apps.makerspaces.profile_images._swap": "Runs inside the authenticated member profile image route.",
    "apps.tenant_migration.tenant_dump_cleanup.cleanup_refused_tenant_dump_artifacts": (
        "Deletes only private Lane D coordination artifacts after a refused run."
    ),
    "apps.tenant_migration.tenant_dump_publication._delete_unpublished": (
        "Post-commit cleanup of a refused Lane D coordination artifact."
    ),
    "apps.tenant_migration.tenant_dump_publication._discard_failed_registration": (
        "Fail-closed cleanup of an unpublished Lane D coordination artifact."
    ),
    "apps.tenant_migration.tenant_dump_publication.register_unpublished_artifact": (
        "Offline Lane D sealing writes only a private publication-staging object."
    ),
    "apps.tenant_migration.services_export_job.run_migration_export_job": (
        "The migration export lifecycle owns source_archive_write while uploading."
    ),
}
