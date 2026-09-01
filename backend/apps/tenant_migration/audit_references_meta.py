"""AuditLog metadata reference declarations for portable tenant archives."""

from .audit_references_targets import (
    AuditReference,
    AuditReferenceDisposition,
)


def _reference(disposition, model, *edges):
    return {
        edge: AuditReference(disposition, model)
        for edge in edges
    }


R = AuditReferenceDisposition.REMAP
S = AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT

# Literal id-bearing paths currently visible to the AST guard.  Source-local entries
# name no PK map because they are provider identifiers, omitted-model identifiers, or
# polymorphic references whose live binding must not be asserted.
AUDIT_META_REFERENCES = {
    **_reference(R, "apiclients.ApiKeyRequest", ("api_client.created", "api_key_request_id")),
    **_reference(R, "apiclients.ApiClient", ("api_key_request.approved", "api_client_id")),
    **_reference(
        R, "boxes.QrCode", ("asset.issued", "qr_id"),
        ("public_tool.checked_out", "qr_id"), ("public_tool.returned", "qr_id"),
    ),
    **_reference(
        R, "hardware_requests.HardwareRequest",
        ("asset.issued", "request_id"), ("box.scanned", "request_id"),
        ("evidence.attached", "request_id"),
        ("machine_service.consumption_recorded", "request_id"),
        ("problem_report.triaged", "request_id"),
        ("public_tool.problem_reported", "request_id"),
    ),
    **_reference(
        R, "hardware_requests.HardwareRequestItem",
        ("asset.issued", "request_item_id"),
        ("request.accepted", "accepted.<keys>"),
    ),
    **_reference(
        R, "boxes.Box", ("box.assigned", "box_id"),
        ("box.scanned", "box_id"), ("request.issued", "box_id"),
    ),
    **_reference(
        R, "evidence.EvidencePhoto", ("evidence.attached", "evidence_id"),
        ("problem_report.triaged", "evidence_id"),
        ("request.issued", "evidence_id"),
    ),
    **_reference(R, "hardware_requests.ReturnEvent", ("evidence.attached", "return_event_id")),
    **_reference(R, "events.EventRegistration", ("event.host_waiver_accepted", "registration_id")),
    # Removing an organizer names the event it was removed from. REMAP, matching the
    # sibling above: an Event is tenant-owned and travels with the export, so the id is
    # remappable. The created/updated siblings pick their action with a conditional, so
    # the AST guard reports them as dynamic rather than as declared paths.
    **_reference(
        R, "events.Event",
        # All three organizer actions, not just the one the AST guard can see. The guard
        # only discovers literal action strings, and created/updated are chosen with a
        # conditional -- but portable import remaps meta ids by EXACT action/path, so an
        # undeclared action would carry a SOURCE event id into the target and could point
        # an append-only audit row at an unrelated event.
        ("event.organizer_created", "event_id"),
        ("event.organizer_updated", "event_id"),
        ("event.organizer_deleted", "event_id"),
    ),
    **_reference(
        R, "makerspaces.MakerspaceWaiver",
        ("event.host_waiver_accepted", "host_waiver_id"),
        ("membership.waiver_accepted", "waiver_id"),
        ("membership.waiver_witnessed", "waiver_id"),
    ),
    **_reference(R, "inventory.InventoryAsset", ("inventory.asset_moved_makerspace", "asset_id")),
    **_reference(
        R, "inventory.InventoryProduct",
        ("inventory.asset_moved_makerspace", "dest_product_id"),
        ("inventory.asset_updated", "product_id"),
        ("procurement.moved_to_inventory", "product_id"),
    ),
    **_reference(
        R, "machines.Machine", ("machine.typed_usage_logged", "machine_id"),
        ("maintenance.document_added", "machine_id"),
        ("maintenance.document_deleted", "machine_id"),
        ("maintenance.schedule_created", "machine_id"),
        ("maintenance.schedule_deactivated", "machine_id"),
    ),
    **_reference(R, "machines.MachineUsageEntry", ("machine.typed_usage_logged", "usage_entry_id")),
    **_reference(
        R, "machines.MachineServiceRequest",
        ("machine_service.file_attached", "request_id"),
        ("machine_service.file_staged", "request_id"),
    ),
    **_reference(
        R, "machines.ServiceRequestFile",
        ("machine_service.file_attached", "file_id"),
        ("machine_service.file_deleted", "file_id"),
        ("machine_service.file_staged", "file_id"),
    ),
    **_reference(R, "machines.ServiceQueue", ("machine_service.file_staged", "queue_id")),
    **_reference(
        R, "maintenance.MaintenanceLog",
        ("maintenance.document_added", "log_id"),
        ("maintenance.document_deleted", "log_id"),
        ("maintenance.schedule_completed", "log_id"),
    ),
    **_reference(
        R, "maintenance.MaintenanceLogDocument",
        ("maintenance.document_deleted", "document_id"),
    ),
    **_reference(
        R, "makerspaces.MakerspaceRole", ("membership.invited", "role_id"),
        ("membership.referred", "role_id"), ("membership.role_changed", "role_id"),
        ("role.created", "id"), ("staff.role_assigned", "new_role_id"),
        ("staff.role_assigned", "old_role_id"),
    ),
    **_reference(
        R, "makerspaces.MakerspaceMembership",
        ("membership.waiver_witnessed", "membership_id"),
        ("staff.role_assigned", "membership_id"),
    ),
    **_reference(
        R, "integrations.NotificationDestination",
        ("notification.destination_updated", "destination_id"),
    ),
    **_reference(
        R, "payments.Payment", ("payment.checkout_created", "payment_id"),
        ("payment.created", "payment_id"),
    ),
    **_reference(
        R, "hardware_requests.PublicToolLoan",
        ("problem_report.triaged", "loan_id"),
        ("public_problem.resolved", "loan_id"),
        ("public_tool.problem_reported", "loan_id"),
    ),
    **_reference(R, "machines.MachineConsumablePool", ("procurement.low_stock_flagged", "pool_id")),
    **_reference(
        R, "procurement.ToBuyItem",
        ("procurement.low_stock_flagged", "to_buy_item_id"),
        ("procurement.moved_to_inventory", "item_id"),
        ("procurement.moved_to_printing", "item_id"),
    ),
    **_reference(R, "operations.StocktakeLine", ("stocktake.line_counted", "line_id")),
}

_SOURCE_LOCAL_EDGES = {
    ("audit.signing_key_rotation_aborted", "rotation_id"),
    ("audit.signing_key_rotation_started", "rotation_id"),
    ("audit.signing_key_rotation_completed", "rotation_id"),
    ("audit.signing_key_rotation_failed", "rotation_id"),
    ("encryption.write_fence_closed", "operation_id"),
    ("encryption.write_fence_opened", "operation_id"),
    ("payment.checkout_created", "subject_id"),
    ("payment.created", "subject_id"),
    ("payment.double_paid_refund_required", "event_id"),
    ("payment.paid_after_terminal", "event_id"),
    ("payment.paid_online", "event_id"),
    ("payments.connect_authorization_revoked", "connect_account_id"),
    ("payments.connect_previous_authorization_revoked", "connect_account_id"),
    ("procurement.moved_to_printing", "result_id"),
    ("qr.rebound", "new_target_id"),
    ("tenant_migration.pairing_approved", "migration_id"),
    ("tenant_migration.pairing_approved", "source_deployment_id"),
    ("tenant_migration.pairing_approved", "target_deployment_id"),
    ("tenant_migration.source_migrated_out", "migration_id"),
    ("tenant_migration.source_migrated_out", "receipt_id"),
    ("tenant_migration.source_migrated_out", "source_deployment_id"),
    ("tenant_migration.source_migrated_out", "target_deployment_id"),
    ("tenant_migration.target_activated", "migration_id"),
    ("tenant_migration.target_activated", "receipt_id"),
    ("tenant_migration.target_activated", "source_deployment_id"),
    ("tenant_migration.target_activated", "target_deployment_id"),
    ("tenant_migration.target_aborted", "migration_id"),
    ("tenant_migration.target_aborted", "receipt_id"),
    ("tenant_migration.target_aborted", "source_deployment_id"),
    ("tenant_migration.target_aborted", "target_deployment_id"),
    ("tenant_migration.source_reopened", "migration_id"),
    ("tenant_migration.source_reopened", "receipt_id"),
    ("tenant_migration.source_reopened", "source_deployment_id"),
    ("tenant_migration.source_reopened", "target_deployment_id"),
    ("tenant_migration.source_gate_closed", "owner_id"),
    ("tenant_migration.source_gate_capture_released", "owner_id"),
    ("tenant_migration.source_gate_recovered", "owner_id"),
    ("tenant_migration.source_gate_reopened", "owner_id"),
    ("tenant_migration.source_gate_recovery_command", "makerspace_id"),
    ("tenant_migration.source_gate_recovery_command", "owner_id"),
    ("tenant_migration.source_gate_migrated_out", "owner_id"),
    ("tenant_migration.source_quiesced", "owner_id"),
    ("tenant_migration.tenant_dump_captured", "gate_owner_id"),
    ("tenant_migration.tenant_dump_derived", "artifact_id"),
    ("tenant_migration.tenant_dump_derived", "capture_id"),
    ("tenant_migration.objects_staged", "job_id"),
    ("tenant_migration.objects_promoted", "job_id"),
    ("tenant_migration.objects_rolled_back", "job_id"),
    ("tenant_migration.export_requested", "export_id"),
    ("tenant_migration.export_read", "export_id"),
    ("data_export.download_url_issued", "export_id"),
    ("data_export.downloaded", "export_id"),
    ("evidence.object_expired", "sweep_run_id"),
    ("tenant_migration.import_created", "import_id"),
    ("tenant_migration.import_read", "import_id"),
    ("tenant_migration.import_run_requested", "import_id"),
    ("tenant_migration.identity_decisions_submitted", "import_id"),
    ("tenant_migration.identity_decisions_read", "import_id"),
    ("tenant_migration.import_completed", "import_id"),
    ("tenant_migration.verification_read", "import_id"),
    # Lane E compound-artifact identifiers. Deployment-operational: the artifact
    # and component ledger rows never travel, so there is no PK to remap and the
    # live binding must not be asserted on a target.
    ("backup.archive_exclusion_activated", "artifact_id"),
    ("backup.archive_exclusion_activated", "capture_id"),
}
AUDIT_META_REFERENCES.update(_reference(S, None, *_SOURCE_LOCAL_EDGES))
AUDIT_META_REFERENCES.update(
    _reference(
        S, "backup.RestoreOperation",
        ("backup.quarantine_acknowledged", "restore_id"),
    )
)
AUDIT_META_REFERENCES.update(
    _reference(S, "integrations.EmailLog", ("email.retried", "email_log_id"))
)
AUDIT_META_REFERENCES.update(
    _reference(
        S, "accounts.User", ("encryption.write_fence_closed", "actor_id"),
        ("encryption.write_fence_opened", "actor_id"),
    )
)
# Revoking an organization membership names the person it revoked. SOURCE_LOCAL_SNAPSHOT
# rather than REMAP because the membership itself is an omitted model that never travels
# with a tenant, so asserting a live binding for the id it mentions would be a claim the
# archive cannot keep. Sibling created/updated events emit the same key but pick their
# action with a conditional expression, so the AST guard reports them as dynamic rather
# than as declared paths.
AUDIT_META_REFERENCES.update(
    _reference(
        S, "accounts.User", ("organization.membership_deleted", "user_id"),
    )
)
AUDIT_META_REFERENCES.update(
    _reference(
        S, "makerspaces.Makerspace",
        ("event.host_waiver_accepted", "via_makerspace_id"),
        ("inventory.asset_moved_makerspace", "new_makerspace_id"),
        ("inventory.asset_moved_makerspace", "old_makerspace_id"),
        ("payment.created", "via_makerspace_id"),
        ("qr.rebound", "new_makerspace_id"),
        ("stock_transfer.received", "source_makerspace_id"),
    )
)
AUDIT_META_REFERENCES.update(
    _reference(
        S, "makerspaces.MakerspaceArchiveRequest",
        ("makerspace.archive_request_approved", "archive_request_id"),
        ("makerspace.archive_request_declined", "archive_request_id"),
        ("makerspace.archive_request_withdrawn", "archive_request_id"),
        ("makerspace.archive_requested", "archive_request_id"),
    )
)
AUDIT_META_REFERENCES.update(
    _reference(
        S, "payments.ProcessedStripeEvent",
        ("payment.checkout_expired", "stripe_event_id"),
        ("payment.double_paid_refund_required", "stripe_event_id"),
        ("payment.paid_after_terminal", "stripe_event_id"),
        ("payment.paid_online", "stripe_event_id"),
    )
)
AUDIT_META_REFERENCES.update(
    _reference(
        S, "accounts.MemberClaimCode",
        ("presence.ended_claim_revoked", "claim_session_id"),
    )
)
AUDIT_META_REFERENCES.update(
    _reference(S, "boxes.QrScanEvent", ("qr.scanned", "scan_id"))
)
