"""Relational and semantic reference registries for the global User closure."""

from .fields import FIELDS
from .models import EXPORTED_MODELS
from .types import (
    Fidelity,
    Omitted,
    SemanticUserRef,
    SourceLocalProvenance,
    UserEdge,
)


class DanglingUserReferenceError(RuntimeError):
    """A raw user ID cannot be bound safely in a portable archive."""
def require_raw_user(fidelity, *, model, row_pk, field, user_id, existing_user_ids):
    """Enforce the declared no-dangling contract before a raw ID is remapped."""
    if fidelity is Fidelity.PORTABLE and user_id not in existing_user_ids:
        raise DanglingUserReferenceError(
            f"{model} row {row_pk} has dangling {field}={user_id}"
        )
    return user_id
RAW_USER_REFERENCE_FIELDS = frozenset(  # Raw integers are not discoverable as FKs.
    {
        ("encryption.PiiGlobalWriteFence", "actor_id"),
        ("encryption.PiiMakerspaceWriteFence", "actor_id"),
        ("machines.ServiceRequestFile", "owner_user_id"),
    }
)

# Every forward relation to accounts.User in the internal model graph, including M2M.
RELATIONAL_USER_FIELDS = frozenset(
    {
        ("accounts.DeviceGrant", "user"),
        ("accounts.DeviceRefreshFamily", "user"),
        ("accounts.NativeAppRegistration", "approved_by"),
        ("accounts.EmailVerificationChallenge", "user"),
        ("accounts.PhoneVerificationChallenge", "user"),
        ("accounts.SocialIdentity", "user"),
        ("admin_api.BulkImportJob", "actor"),
        # Phase 5A deployment models still need declarations because the guard scans
        # every internal model, not only exported ones.
        ("backup.BackupArchive", "requested_by"),
        ("backup.DeploymentRecoveryState", "acknowledged_by"),
        ("backup.DeploymentRecoveryState", "recovery_principal"),
        ("backup.MakerspaceArchiveRecipient", "added_by"),
        ("backup.ArchiveCustodyAlarmDelivery", "recipient_user"),
        ("backup.TenantExitCustodyAlarmDelivery", "recipient_user"),
        ("backup.RestoreOperation", "requested_by"),
        ("data_export.DataExportJob", "requested_by"),
        ("data_export.DataExportJob", "download_issued_to"),
        ("apiclients.ApiClient", "created_by"),
        ("apiclients.ApiKeyRequest", "requester"),
        ("apiclients.ApiKeyRequest", "resolved_by"),
        ("audit.AuditLog", "actor"),
        ("bookings.BookableSpace", "created_by"),
        ("bookings.Booking", "member"),
        ("boxes.BoxScan", "actor"),
        ("boxes.QrCode", "created_by"),
        ("boxes.QrScanEvent", "actor"),
        ("events.Event", "created_by"),
        ("events.EventCollaborator", "invited_by"),
        ("events.EventCollaborator", "responded_by"),
        ("events.EventOrganizer", "created_by"),
        ("events.EventRegistration", "member"),
        ("evidence.EvidencePhoto", "uploaded_by"),
        ("hardware_requests.HardwareRequest", "requester"),
        ("hardware_requests.HardwareRequest", "accepted_by"),
        ("hardware_requests.HardwareRequest", "issued_by"),
        ("hardware_requests.HardwareRequest", "closed_by"),
        ("hardware_requests.PublicProblemReport", "requester"),
        ("hardware_requests.PublicProblemReport", "resolved_by"),
        ("hardware_requests.PublicToolLoan", "requester"),
        ("hardware_requests.RequesterAccountability", "requester"),
        ("hardware_requests.RequesterAccountability", "created_by"),
        ("hardware_requests.ReturnEvent", "actor"),
        ("integrations.ChatTemplate", "updated_by"),
        ("integrations.EmailNotificationMute", "created_by"),
        ("integrations.NotificationPreference", "updated_by"),
        ("integrations.NotificationRecipient", "user"),
        ("integrations.NotificationRecipient", "created_by"),
        ("integrations.PushDevice", "user"),
        ("machines.Machine", "created_by"),
        ("machines.MachineConsumable", "created_by"),
        ("machines.MachineConsumableAdjustment", "created_by"),
        ("machines.MachineConsumablePool", "created_by"),
        ("machines.MachineDocument", "uploaded_by"),
        ("machines.MachineErrorLog", "logged_by"),
        ("machines.MachineOperator", "user"),
        ("machines.MachineOperator", "assigned_by"),
        ("machines.MachineServiceRequest", "requester"),
        ("machines.MachineServiceRequest", "member"),
        ("machines.MachineServiceRequest", "handled_by"),
        ("machines.MachineServiceRequest", "accepted_by"),
        ("machines.MachineServiceRequest", "collected_by"),
        ("machines.MachineUsageEntry", "logged_by"),
        ("machines.MakerspaceMachineTypePricing", "created_by"),
        ("machines.MakerspaceMachineTypePricing", "updated_by"),
        ("machines.PrintingCutoverRepair", "resolved_by"),
        ("machines.ServiceRequestConsumption", "created_by"),
        ("maintenance.MaintenanceLog", "performed_by"),
        ("maintenance.MaintenanceLogDocument", "uploaded_by"),
        ("maintenance.MaintenanceSchedule", "created_by"),
        ("makerspaces.Makerspace", "created_by"),
        ("makerspaces.Makerspace", "archived_by"),
        ("makerspaces.MakerspaceArchiveRequest", "requested_by"),
        ("makerspaces.MakerspaceArchiveRequest", "resolved_by"),
        ("accounts.PasswordResetEnvelope", "user"),
        ("accounts.MemberClaimCode", "issued_by"),
        ("accounts.MemberClaimCode", "revoked_by"),
        ("accounts.OidcBrowserAttempt", "intended_user"),
        ("makerspaces.Makerspace", "anonymous_requester"),
        ("makerspaces.MakerspaceMembership", "user"),
        ("makerspaces.MakerspaceMembership", "verified_by"),
        ("makerspaces.MakerspaceMembership", "activated_by"),
        ("makerspaces.MakerspaceMembership", "revoked_by"),
        # Phase 7: the staff actor who witnessed a waiver acceptance in person.
        ("makerspaces.MakerspaceMembership", "witnessed_by"),
        # Phase 7 import machinery. The model itself is omitted, but the edge is
        # declared so user-edge completeness stays a total check over the graph.
        ("makerspaces.ImportedUserReconciliation", "target_user"),
        # Omitted Phase 5B coordination still declares every account edge; model-level
        # omission does not decide whether an account belongs in the user closure.
        ("tenant_migration.TenantImportJob", "actor"),
        ("tenant_migration.ImportIdentityDecision", "target_user"),
        ("tenant_migration.DisclosureClosureApproval", "approved_by"),
        ("tenant_migration.DisclosureClosureApproval", "revoked_by"),
        ("tenant_migration.MigrationPairing", "approved_by"),
        ("tenant_migration.ReceiptConsumption", "consumed_by"),
        ("tenant_migration.MigratedOutHandoff", "reopened_by"),
        # Source-gate ownership is excluded from every tenant archive and user closure.
        ("tenant_migration.SourceMigrationGate", "actor"),
        ("tenant_migration.TenantDumpCapture", "requested_by"),
        ("makerspaces.MakerspaceWaiver", "created_by"),
        ("makerspaces.MembershipRequest", "user"),
        ("makerspaces.MembershipRequest", "requested_by"),
        ("makerspaces.MembershipRequest", "invited_by"),
        ("makerspaces.MembershipRequest", "decided_by"),
        ("makerspaces.SubdomainRequest", "requested_by"),
        ("makerspaces.SubdomainRequest", "decided_by"),
        ("operations.InventoryAdjustment", "created_by"),
        ("operations.QrPrintBatch", "created_by"),
        ("operations.StocktakeLedgerEntry", "created_by"),
        ("operations.StocktakeSession", "started_by"),
        ("operations.StocktakeSession", "approved_by"),
        ("operations.StockTransfer", "created_by"),
        ("organizations.Organization", "created_by"),
        ("organizations.OrganizationMakerspace", "created_by"),
        ("organizations.OrganizationMembership", "user"),
        ("organizations.OrganizationMembership", "created_by"),
        ("organizations.OrganizationInvitation", "created_by"),
        ("organizations.OrganizationInvitation", "redeemed_by"),
        ("payments.Payment", "member"),
        ("payments.Payment", "created_by"),
        ("payments.StripeConnectOAuthState", "initiated_by"),
        ("presence.PresenceSession", "member"),
        ("presence.PresenceSession", "ended_by"),
        ("procurement.ToBuyItem", "purchaser"),
        ("procurement.ToBuyItem", "created_by"),
        ("procurement.ToBuyReceipt", "uploaded_by"),
        ("warranty.WarrantyDocument", "uploaded_by"),
    }
)

USER_EDGES = {}
_EXCLUDED_USER_EDGE_REASONS = {
    ("tenant_migration.TenantImportJob", "actor"): (
        "Target-side import coordination attribution must not contribute to a tenant "
        "archive's global user closure."
    ),
    ("tenant_migration.SourceMigrationGate", "actor"): (
        "Deployment-scoped source-gate ownership must not contribute to a tenant "
        "archive's global user closure."
    ),
    ("tenant_migration.TenantDumpCapture", "requested_by"): "Source capture coordination must not contribute to a tenant archive's user closure.",
}
for _fidelity in Fidelity:
    for _label, _field in RELATIONAL_USER_FIELDS | RAW_USER_REFERENCE_FIELDS:
        disposition = FIELDS.get((_fidelity, _label, _field))
        included = _label in EXPORTED_MODELS and not isinstance(disposition, Omitted)
        USER_EDGES[(_fidelity, _label, _field)] = UserEdge(
            included=included,
            raw=(_label, _field) in RAW_USER_REFERENCE_FIELDS,
            reason=(
                "Pull the referenced person into the bounded user closure."
                if included
                else _EXCLUDED_USER_EDGE_REASONS.get(
                    (_label, _field),
                    "The source model or field is excluded at this fidelity.",
                )
            ),
        )

POLYMORPHIC_PAIRS = frozenset(
    {
        ("audit.AuditLog", "target_type+target_id"),
        ("boxes.QrCode", "target_type+target_id"),
        ("hardware_requests.PublicToolLoan", "target_type+target_id"),
        ("operations.QrPrintBatchItem", "target_type+target_id"),
    }
)

JSON_FIELDS = frozenset(
    {
        ("apiclients.ApiClient", "scopes"),
        ("apiclients.ApiClient", "allowed_origins"),
        ("apiclients.ApiKeyRequest", "allowed_origins"),
        ("audit.AuditLog", "meta"),
        # Phase 7 imported-actor provenance. Each holds actor_username,
        # actor_display, source_user_id and recorded_at.
        ("makerspaces.MakerspaceMembership", "witnessed_actor_snapshot"),
        ("makerspaces.MakerspaceMembership", "verified_actor_snapshot"),
        ("makerspaces.MakerspaceMembership", "activated_actor_snapshot"),
        ("makerspaces.MakerspaceMembership", "revoked_actor_snapshot"),
        ("bookings.BookableSpace", "custom_form"),
        ("bookings.Booking", "custom_answers"),
        ("events.Event", "custom_form"),
        ("events.EventRegistration", "custom_answers"),
        ("hardware_requests.PublicToolLoan", "asset_ids"),
        ("hardware_requests.PublicToolLoan", "qr_ids"),
        ("machines.Machine", "service_file_policy"),
        ("machines.Machine", "type_payload"),
        ("machines.MachineServiceRequest", "capability_payload"),
        ("machines.MachineType", "capability_config"),
        ("makerspaces.Makerspace", "cors_allowed_origins"),
        ("makerspaces.Makerspace", "enabled_modules"),
        ("makerspaces.Makerspace", "enabled_features"),
        ("makerspaces.Makerspace", "resource_limit_overrides"),
        ("makerspaces.Makerspace", "theme_config"),
        ("makerspaces.Makerspace", "branding_config"),
        ("makerspaces.Makerspace", "presence_preset_minutes"),
        ("makerspaces.MakerspaceRole", "granted_actions"),
        ("makerspaces.MemberProfile", "interests"),
        ("makerspaces.MemberProfile", "languages"),
        ("makerspaces.MemberProfile", "education"),
        ("makerspaces.MemberProject", "links"),
        ("tenant_migration.ExternalTenantReference", "snapshot"),
    }
)

SEMANTIC_REFERENCES = {}
for _fidelity in Fidelity:
    # PORTABLE keeps audit targets as inert source provenance, so it does not pull user
    # targets into the global closure. REDACTED remains shipped operator-facing behavior;
    # narrowing it would silently drop people from an existing export.
    SEMANTIC_REFERENCES[(_fidelity, "audit.AuditLog", "target_type+target_id")] = (
        (
            SemanticUserRef(
                "audit.AuditLog",
                "target_type=accounts.user + target_id",
                "A user audit target joins the REDACTED user closure, as shipped.",
            ),
            SourceLocalProvenance(
                "audit.AuditLog",
                "target_type!=accounts.user + target_id",
                "Non-user polymorphic targets retain their source model label.",
            ),
        )
        if _fidelity is Fidelity.REDACTED
        else (
            SourceLocalProvenance(
                "audit.AuditLog",
                "target_type + target_id",
                "The audit target registry decides remap versus inert source provenance.",
            ),
        )
    )
    for _model, _location in POLYMORPHIC_PAIRS - {
        ("audit.AuditLog", "target_type+target_id")
    }:
        SEMANTIC_REFERENCES[(_fidelity, _model, _location)] = (
            SourceLocalProvenance(
                _model, _location, "Physical/domain target IDs are source-local provenance."
            ),
        )
    for _model, _field in JSON_FIELDS:
        if (_model, _field) == ("audit.AuditLog", "meta"):
            decision = SourceLocalProvenance(
                _model,
                "meta id-bearing paths",
                "The per-action audit registry remaps or source-namespaces every ID path.",
            )
        elif _field.endswith("_actor_snapshot"):
            # `source_user_id` here is deliberately NOT a live reference: Phase 7 v13
            # made imported actor references typed TEXT snapshots precisely because the
            # source user may not exist at the target or may map to a different person.
            # Remapping it would bind evidence to the wrong human, so it stays
            # source-local at BOTH fidelities.
            decision = SourceLocalProvenance(
                _model,
                f"{_field}.source_user_id",
                "Imported actor provenance is source-local text and is never remapped.",
            )
        else:
            decision = SourceLocalProvenance(
                _model,
                f"{_field}.*_id",
                "Reviewed JSON schema contains no live user reference at this fidelity.",
            )
        SEMANTIC_REFERENCES[(_fidelity, _model, f"json:{_field}")] = (decision,)
