"""Models a tenant export references globally or omits, each with its reason.

Split out of ``classification`` by line range; the entries are unchanged.
"""

from .types import GlobalReference

GLOBAL_MODELS = {
    "accounts.User": GlobalReference(
        "Only the user closure is projected; the platform-global table is never tenant-owned."
    ),
    "organizations.Organization": GlobalReference(
        "Platform-level organizations are referenced by tenant links but are never tenant-owned."
    ),
}

OMITTED_MODELS = {
    "hardware_requests.ReplayCommand": "Short-lived Station/session replay coordination; physical results and evidence travel independently.",
    "makerspaces.StationCredential": (
        "Live Station authentication authority; a portable tenant must rotate a new PIN."
    ),
    "makerspaces.StationOperatorLease": (
        "Transient kiosk operator authority bound to one live Station session."
    ),
    "makerspaces.StationSessionRevocation": (
        "Deny-only transient record of ended kiosk Station sessions."
    ),
    "events.MemberCalendarFeed": (
        "Deployment-local bearer credential over member registration history; restored tenants must reissue it."
    ),
    "apiclients.ApiClientImportApproval": "Artifact-bound target authority approval is deployment-local coordination state.",
    "accounts.DailyOtpEmailCounter": "Platform authentication telemetry.",
    "accounts.DeviceAttestationChallenge": "Transient authentication state.",
    "accounts.DeviceGrant": "Live bearer-session authority.",
    "accounts.DeviceRefreshFamily": "Live bearer-session authority.",
    "accounts.DeviceRefreshToken": "Live bearer-session authority.",
    "accounts.EmailVerificationChallenge": "Transient authentication state.",
    "accounts.OidcProvider": "Platform identity configuration.",
    # Phase 7 named both of these omitted-as-transient when it was planned: a claim
    # code is a short-lived bearer credential stored only as a digest, and a browser
    # attempt holds a live PKCE verifier and two more secrets.
    "accounts.MemberClaimCode": "Transient authentication state.",
    "accounts.NativeAppRegistration": (
        "Live application authorization and deployment-local verifier binding."
    ),
    "accounts.OidcBrowserAttempt": "Transient authentication state.",
    # Phase 8. One row per submitted address -- including addresses that belong to
    # nobody, since anyone can create one by asking for a reset -- holding a live OTP
    # digest and a credential fingerprint. Transient authentication state, and global
    # rather than tenant data.
    "accounts.PasswordResetEnvelope": "Transient authentication state.",
    "accounts.PhoneVerificationChallenge": "Transient authentication state.",
    "accounts.PlatformLoginMethods": "Platform identity configuration.",
    "accounts.PlatformSocialAuthSettings": "Platform credentials and identity configuration.",
    "accounts.SocialIdentity": "Verified platform login identity.",
    "accounts.SocialLoginNonce": "Transient authentication state.",
    "admin_api.BulkImportJob": "Arbitrary upload and unschematized JSON rows.",
    "audit.AuditMacKey": "Deployment-local audit integrity key material.",
    "audit.AuditBatch": "Deployment-local externally anchored attestation state.",
    "audit.AuditBatchLeaf": "Deployment-local externally anchored attestation membership.",
    "audit.AuditSigningKey": "Deployment-local audit signing authority.",
    "audit.AuditSigningKeyRotation": (
        "Deployment-local omitted audit signing-key transition integrity material."
    ),
    "audit.AuditSigningKeyRotationEvent": (
        "Deployment-local omitted audit signing-key lifecycle integrity material."
    ),
    "audit.AuditVerificationRun": (
        "Source-deployment verification request: its truth is tied to this deployment's "
        "keys, anchors and audit row ids, so a target must not inherit it."
    ),
    "audit.AuditVerificationRunEvent": (
        "Source-deployment verification status and aggregate results."
    ),
    "encryption.MakerspaceEncryptionKey": "Encryption key material never enters a manager export.",
    "encryption.PiiBlindIndex": "Deployment-local derived identity index.",
    "encryption.PiiGlobalWriteFence": "Platform coordination state.",
    "encryption.PiiMakerspaceWriteFence": "Deployment coordination state.",
    "encryption.SearchKeyGeneration": "Deployment-local cryptographic state.",
    "evidence.EvidenceAbandonedUploadReceipt": (
        "Deployment coordination: permanent late-write reconciliation and key "
        "reservation for a cleaned never-consumed upload; never handover evidence."
    ),
    "evidence.EvidenceUploadFinalization": (
        "Upload promotion coordination state; the evidence row and its object carry "
        "everything that outlives one upload."
    ),
    "integrations.DailyEmailCounter": "Delivery telemetry.",
    "integrations.DailyNotificationCounter": "Delivery telemetry.",
    "integrations.DailyOtpSmsCounter": "Platform delivery telemetry.",
    "integrations.EmailLog": "Delivery bodies and telemetry are not rebuild data.",
    "integrations.NotificationDeliveryLog": "Delivery payloads and telemetry are not rebuild data.",
    "integrations.PlatformEmailSettings": "Platform credentials.",
    "integrations.PlatformPushSettings": "Platform credentials.",
    "integrations.PlatformSmsSettings": "Platform credentials.",
    "integrations.PushDevice": "Live device bearer destination.",
    "machines.PrintingCutoverRepair": "Retired migration provenance.",
    "machines.PrintingCutoverState": "Retired migration coordination state.",
    "makerspaces.MakerspaceArchiveRequest": "Source-deployment lifecycle request.",
    # Phase 7 import staging. Both are TARGET-side machinery rather than source tenant
    # data: a pending row is an archived membership waiting for its address to be proven
    # here, and a reconciliation is the operator's persisted judgement that an archived
    # person is a particular target account. The readable export omits them (Phase 4 v8
    # section 4); carrying and remapping unresolved pending rows is PORTABLE's job in 5B.
    "makerspaces.PendingImportedMembership": "Import staging awaiting target-side proof.",
    "makerspaces.ImportedUserReconciliation": "Target-side operator reconciliation input.",
    "makerspaces.SubdomainRequest": "Source-deployment routing request.",
    "operations.PeriodicTaskRun": "Deployment scheduler state.",
    "operations.ReportDelivery": "Report delivery telemetry and a short-lived download coordination key; not rebuild data.",
    "operations.ReportRollupCursor": "Rebuildable report rollup coordination and retention-fence state.",
    "events.EventOrganizer": (
        "It references a deployment-global organization that does not travel with "
        "a tenant export."
    ),
    "events.EventSeriesOrganizer": (
        "It references a deployment-global organization that does not travel with "
        "a tenant export."
    ),
    "organizations.OrganizationMakerspace": (
        "Source-deployment organization links do not travel with tenant exports."
    ),
    "organizations.OrganizationMembership": (
        "Live cross-tenant organization authorization."
    ),
    "organizations.OrganizationInvitation": (
        "Deployment-local bearer authorization state for a global organization."
    ),
    "tenant_migration.TenantImportJob": "Target-side tenant import coordination state.",
    "tenant_migration.TenantImportObject": (
        "Deployment-scoped import promotion journal; it names a target makerspace "
        "but is coordination state, not portable tenant data."
    ),
    "tenant_migration.ImportIdentityDecision": "Target-side identity resolution input.",
    "tenant_migration.DisclosureClosureApproval": "Source-side disclosure authorization state.",
    "tenant_migration.TenantMigrationExportJob": "Source-side migration export coordination state.",
    "tenant_migration.DeploymentSigningKey": "Deployment-local private signing authority.",
    "tenant_migration.MigrationPairing": "Deployment-local pinned peer trust configuration.",
    "tenant_migration.MigrationReceipt": "Single-use cross-deployment cutover authority.",
    "tenant_migration.ReceiptConsumption": "Deployment-local receipt replay state.",
    "tenant_migration.MigratedOutHandoff": "Source-deployment tenant lifecycle state.",
    "tenant_migration.SourceMigrationGate": (
        "Source-deployment coordination state must not travel inside a tenant archive."
    ),
    "tenant_migration.TenantDumpCapture": "Source capture, lineage, publication, and download coordination state.",
    "payments.PlatformStripeConnectSettings": "Platform payment credentials.",
    "payments.ProcessedStripeEvent": "Provider idempotency telemetry.",
    "payments.StripeConnectOAuthState": "Transient OAuth state.",
    "roadmap.RoadmapItem": "Platform-global product roadmap.",
    "updates.PlatformUpdateSettings": "Platform update state.",
    "data_export.DataExportJob": "Source-deployment export lifecycle and bearer state.",
    # Phase 5A. Every one of these is deployment-scoped operational state, not tenant data,
    # even where a row names a makerspace: BackupArchive.makerspace records which tenant an
    # archive covers, and exporting that row would carry its single-use download token into
    # a tenant archive. Archives are explicitly outside the purge guarantee, so they must
    # not travel inside one either.
    "backup.BackupArchive": "Deployment archive lifecycle and download bearer state.",
    "backup.ArchiveRecipientReservation": "Deployment-local key-namespace state.",
    "backup.MakerspaceArchiveCustodyState": (
        "Deployment-local archive-custody alarm state, recomputed from recipients."
    ),
    "backup.ArchiveCustodyAlarmDelivery": (
        "Deployment-local custody-alarm delivery and retry state."
    ),
    "backup.MakerspaceTenantExitCustodyState": "Deployment-local Lane D custody state, independently recomputed from recipients.",
    "backup.TenantExitCustodyAlarmDelivery": "Deployment-local Lane D custody alarm delivery and retry state.",
    "backup.BackupLease": "Deployment scheduler lease.",
    "backup.BackupRun": "Deployment backup coverage run state.",
    "backup.BackupRunCoverage": (
        "Deployment backup coverage proof; it names a makerspace but is "
        "deployment coordination state, not portable tenant data."
    ),
    "backup.B1ActivationState": "Deployment-local Lane E activation state.",
    "backup.BackupArtifactLedger": "Durable deployment backup artifact operations.",
    "backup.BackupArtifactComponent": "Durable deployment backup component operations.",
    "backup.BackupComponentRecipient": "Durable recipient-use custody history.",
    "backup.DeploymentDatabaseIdentity": "Deployment-local identity regenerated after restore.",
    "backup.DeploymentRecoveryState": "Deployment recovery and quarantine state.",
    "backup.PlatformBackupSettings": "Platform backup configuration and age recipient.",
    "backup.RestoreOperation": "Deployment restore lifecycle state.",
    "backup.RestoreRollbackObject": "Deployment restore object-rollback journal.",
    "backup.B1RestoreOperationState": "Deployment-local compound-restore stage state.",
    "backup.B1RestoreComponentState": "Deployment-local opaque-slice restore state.",
    "backup.B1ReservationEntry": "Deployment-local restore reservation and fence facts.",
    "backup.B1FenceContinuity": "Deployment-local fence-continuity proof journal.",
    "backup.BackupDestination": "Platform offsite destination with encrypted credentials.",
    "backup.BackupDestinationUpload": (
        "Deployment offsite upload journal; archives are outside the purge guarantee."
    ),
}
