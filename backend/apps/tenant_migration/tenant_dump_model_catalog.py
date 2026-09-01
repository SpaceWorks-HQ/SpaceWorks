"""Exact model/table universes for ``spaceworks-tenant-dump-v1``."""

from apps.data_export.models import OMITTED_MODELS

from .tenant_dump_types import ModelDisposition, ModelRule, TableRule


FIRST_PARTY_APP_LABELS = frozenset(
    """accounts admin_api apiclients audit backup bookings boxes data_export
    encryption events evidence hardware_requests integrations inventory machines
    maintenance makerspaces notifications operations organizations payments presence
    printing procurement roadmap separability tenant_migration updates warranty""".split()
)
THIRD_PARTY_MODEL_APP_LABELS = frozenset(
    {"admin", "auth", "axes", "contenttypes", "sessions", "token_blacklist"}
)
THIRD_PARTY_INSTALLED_APP_LABELS = frozenset(
    """unfold unfold_filters admin auth axes contenttypes postgres sessions messages
    staticfiles rest_framework drf_spectacular rest_framework_simplejwt token_blacklist
    corsheaders storages""".split()
)

# These labels are literal. A new exported model must be placed here deliberately;
# deriving this set from data_export.EXPORTED_MODELS would let it travel before a
# Lane-D-specific review.
PROJECTED_MODEL_LABELS = frozenset(
    """accounts.User apiclients.ApiKeyRequest audit.AuditLog
    backup.MakerspaceArchiveRecipient bookings.BookableSpace bookings.Booking boxes.Box
    boxes.BoxScan boxes.QrCode boxes.QrScanEvent events.EventSeries events.Event events.EventRegistration
    events.EventCheckInEvent events.EventFeedbackSurvey events.EventFeedbackResponse
    events.EventAttendanceCertificate
    evidence.EvidencePhoto hardware_requests.HardwareRequest
    hardware_requests.HardwareRequestItem hardware_requests.HardwareRequestItemAsset
    hardware_requests.PublicProblemReport hardware_requests.PublicToolLoan
    hardware_requests.RequesterAccountability hardware_requests.ReturnEvent
    integrations.ChatTemplate integrations.DestinationCategoryScope
    integrations.DestinationMachineScope integrations.DestinationMachineTypeScope
    integrations.EmailTemplate integrations.MachineTypeEmailTemplate
    integrations.NotificationDestination inventory.Category inventory.InventoryAsset
    inventory.InventoryProduct machines.Machine machines.MachineConsumable
    machines.MachineConsumableAdjustment machines.MachineConsumablePool
    machines.MachineDocument machines.MachineErrorLog machines.MachineServiceRequest
    machines.MachineType machines.MachineUsageEntry
    machines.MakerspaceMachineTypePricing machines.ServiceBucket machines.ServiceQueue
    machines.ServiceRequestConsumption machines.ServiceRequestFile
    maintenance.MaintenanceLog maintenance.MaintenanceLogDocument
    maintenance.MaintenanceSchedule makerspaces.Makerspace
    makerspaces.MakerspaceMembership makerspaces.MakerspaceWaiver
    makerspaces.MemberProfile makerspaces.MemberProject makerspaces.MembershipRequest
    notifications.Notification operations.InventoryAdjustment operations.QrPrintBatch
    operations.QrPrintBatchItem operations.StockTransfer operations.StockTransferLine
    operations.StocktakeLedgerEntry operations.StocktakeLine operations.StocktakeSession
    payments.MakerspacePaymentSettings payments.Payment presence.PresenceSession
    procurement.ToBuyItem procurement.ToBuyReceipt
    tenant_migration.ExternalTenantReference warranty.Warranty
    warranty.WarrantyDocument""".split()
)

PRESERVE_LIVE_MODEL_LABELS = frozenset({"machines.MachineOperator"})

EXPLICIT_DROP_MODEL_REASONS = {
    "apiclients.ApiClient": "Source clients and their bearer secrets never become target authority.",
    "events.EventCollaborator": "Cross-tenant collaboration grants have no target counterpart.",
    "events.EventSeriesCollaborator": "Cross-tenant series collaboration grants have no target counterpart.",
    "integrations.EmailNotificationMute": "Source delivery suppression does not control target mail.",
    "integrations.NotificationPreference": "Target notification defaults are authoritative.",
    "integrations.NotificationRecipient": "Every explicit recipient is a live disclosure rule.",
    "integrations.RecipientCategoryScope": "The owning disclosure recipient is dropped.",
    "integrations.RecipientMachineScope": "The owning disclosure recipient is dropped.",
    "integrations.RecipientMachineTypeScope": "The owning disclosure recipient is dropped.",
    "machines.RoleMachineScope": "Source role scopes must not grant target machine authority.",
    "machines.RoleMachineTypeScope": "Source role scopes must not grant target type authority.",
    "makerspaces.MakerspaceRole": "Source roles are replaced by target-seeded protected defaults.",
    "organizations.Organization": "Organizations are deployment-global and do not travel.",
}


def _model_rules():
    rules = {}

    def add(label, rule):
        if label in rules:
            raise RuntimeError(f"duplicate Lane D first-party model rule: {label}")
        rules[label] = rule

    for label in PROJECTED_MODEL_LABELS:
        add(label, ModelRule(
            ModelDisposition.PROJECT,
            "Tenant row travels only after its explicit Lane D field/row projection.",
        ))
    for label, reason in OMITTED_MODELS.items():
        add(label, ModelRule(ModelDisposition.DROP, reason))
    for label, reason in EXPLICIT_DROP_MODEL_REASONS.items():
        add(label, ModelRule(ModelDisposition.DROP, reason))
    add("machines.MachineOperator", ModelRule(
        ModelDisposition.PRESERVE_LIVE,
        "Owner decision 22: the exact assignment and provenance travel as live authority.",
    ))
    return rules


FIRST_PARTY_MODEL_RULES = _model_rules()

AUTO_CREATED_TABLE_RULES = {
    "auth.Group_permissions": TableRule(
        ModelDisposition.BOOTSTRAP,
        "Target-seeded Django permission membership only; source rows do not travel.",
    ),
    "accounts.User_groups": TableRule(
        ModelDisposition.EMPTY,
        "Imported users receive no source-global group grants.",
    ),
    "accounts.User_user_permissions": TableRule(
        ModelDisposition.EMPTY,
        "Imported users receive no source-global direct permissions.",
    ),
}

THIRD_PARTY_MODEL_RULES = {
    "admin.LogEntry": TableRule(ModelDisposition.EMPTY, "Deployment-local admin history."),
    "auth.Permission": TableRule(ModelDisposition.BOOTSTRAP, "Seeded by target migrations."),
    "auth.Group": TableRule(ModelDisposition.BOOTSTRAP, "Target-owned Django groups."),
    "axes.AccessFailureLog": TableRule(ModelDisposition.EMPTY, "Source authentication telemetry."),
    "axes.AccessAttempt": TableRule(ModelDisposition.EMPTY, "Source authentication telemetry."),
    "axes.AccessAttemptExpiration": TableRule(ModelDisposition.EMPTY, "Source authentication telemetry."),
    "axes.AccessLog": TableRule(ModelDisposition.EMPTY, "Source authentication telemetry."),
    "contenttypes.ContentType": TableRule(ModelDisposition.BOOTSTRAP, "Seeded by target migrations."),
    "sessions.Session": TableRule(ModelDisposition.EMPTY, "Source bearer sessions never travel."),
    "token_blacklist.OutstandingToken": TableRule(ModelDisposition.EMPTY, "Source bearer tokens never travel."),
    "token_blacklist.BlacklistedToken": TableRule(ModelDisposition.EMPTY, "Source bearer-token state never travels."),
}

UNMANAGED_MODEL_RULES = {}
UNOWNED_TABLE_RULES = {
    "django_migrations": TableRule(
        ModelDisposition.BOOTSTRAP,
        "Scratch and target migrations seed their own schema ledger.",
    ),
    "spaceworks_cache": TableRule(
        ModelDisposition.EMPTY,
        "Discard source cache/throttle rows; runtime repopulates the empty target table.",
    )
}
