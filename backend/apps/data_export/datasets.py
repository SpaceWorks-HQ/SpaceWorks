"""Per-fidelity dataset/output registry."""

from django.apps import apps

from .fields import FIELDS
from .models import EXPORTED_MODELS
from .types import Column, Dataset, Fidelity, Omitted, TenantPredicate, Transformed

P = TenantPredicate

# A dataset has one root model.  Relationship values are IDs/snapshots; a dataset may
# never expand a routing relation into the related tenant's row.
DATASET_SPECS = {
    "apiclients.ApiClient": ("makerspace/api_clients.csv", P(("makerspace",))),
    "apiclients.ApiKeyRequest": ("makerspace/api_key_requests.csv", P(("makerspace",))),
    "audit.AuditLog": ("audit/audit_log.csv", P(("makerspace",))),
    "bookings.BookableSpace": ("bookings/spaces.csv", P(("makerspace",))),
    "bookings.Booking": ("bookings/bookings.csv", P(("space__makerspace",))),
    "boxes.Box": ("inventory/containers_and_boxes.csv", P(("makerspace",))),
    "boxes.BoxScan": ("lending/box_scans.csv", P(("makerspace",), ("box__makerspace",))),
    "boxes.QrCode": ("inventory/qr_mappings.csv", P(("makerspace",))),
    "boxes.QrScanEvent": ("lending/qr_scan_events.csv", P(("makerspace",), ("qr_code__makerspace",))),
    "events.Event": ("events/events.csv", P(("makerspace",))),
    "events.EventCollaborator": ("events/collaborators.csv", P(("event__makerspace", "makerspace"))),
    "events.EventRegistration": ("events/registrations.csv", P(("event__makerspace",))),
    "evidence.EvidencePhoto": ("evidence/photos.csv", P(("makerspace",))),
    "hardware_requests.HardwareRequest": ("lending/requests.csv", P(("makerspace",))),
    "hardware_requests.HardwareRequestItem": ("lending/request_items.csv", P(("request__makerspace",))),
    "hardware_requests.HardwareRequestItemAsset": ("lending/request_item_assets.csv", P(("request_item__request__makerspace",))),
    "hardware_requests.PublicProblemReport": ("lending/problem_reports.csv", P(("makerspace",))),
    "hardware_requests.PublicToolLoan": ("lending/direct_and_self_checkout_loans.csv", P(("makerspace",))),
    "hardware_requests.RequesterAccountability": ("lending/accountability.csv", P(("makerspace",))),
    "hardware_requests.ReturnEvent": ("lending/return_events.csv", P(("makerspace",))),
    "integrations.ChatTemplate": ("notifications/chat_templates.csv", P(("makerspace",))),
    "integrations.DestinationCategoryScope": ("notifications/destination_category_scopes.csv", P(("destination__makerspace",), ("category__makerspace",))),
    "integrations.DestinationMachineScope": ("notifications/destination_machine_scopes.csv", P(("destination__makerspace",), ("machine__makerspace",))),
    "integrations.DestinationMachineTypeScope": ("notifications/destination_machine_type_scopes.csv", P(("destination__makerspace",), ("machine_type__makerspace",))),
    "integrations.EmailNotificationMute": ("notifications/email_mutes.csv", P(("makerspace",))),
    "integrations.EmailTemplate": ("notifications/email_templates.csv", P(("makerspace",))),
    "integrations.MachineTypeEmailTemplate": ("notifications/machine_type_email_templates.csv", P(("makerspace",), ("machine_type__makerspace",))),
    "integrations.NotificationDestination": ("notifications/destinations.csv", P(("makerspace",))),
    "integrations.NotificationPreference": ("notifications/preferences.csv", P(("makerspace",))),
    "integrations.NotificationRecipient": ("notifications/recipients.csv", P(("makerspace",))),
    "integrations.RecipientCategoryScope": ("notifications/recipient_category_scopes.csv", P(("recipient__makerspace",), ("category__makerspace",))),
    "integrations.RecipientMachineScope": ("notifications/recipient_machine_scopes.csv", P(("recipient__makerspace",), ("machine__makerspace",))),
    "integrations.RecipientMachineTypeScope": ("notifications/recipient_machine_type_scopes.csv", P(("recipient__makerspace",), ("machine_type__makerspace",))),
    "inventory.Category": ("inventory/categories.csv", P(("makerspace",))),
    "inventory.InventoryAsset": ("inventory/assets.csv", P(("makerspace",), ("product__makerspace", "box__makerspace"))),
    "inventory.InventoryProduct": ("inventory/products.csv", P(("makerspace",), ("box__makerspace", "category__makerspace"))),
    "machines.Machine": ("machines/machines.csv", P(("makerspace",), ("machine_type__makerspace",))),
    "machines.MachineConsumable": ("machines/consumables.csv", P(("machine__makerspace",), ("product__makerspace",))),
    "machines.MachineConsumableAdjustment": ("machine_service/consumable_adjustments.csv", P(("makerspace",), ("consumable_pool__makerspace",))),
    "machines.MachineConsumablePool": ("machine_service/consumable_pools.csv", P(("makerspace",), ("machine__makerspace",))),
    "machines.MachineDocument": ("machines/documents.csv", P(("machine__makerspace",))),
    "machines.MachineErrorLog": ("machines/error_logs.csv", P(("machine__makerspace",))),
    "machines.MachineOperator": ("machines/operators.csv", P(("machine__makerspace",))),
    "machines.MachineServiceRequest": ("machine_service/requests.csv", P(("makerspace",))),
    "machines.MachineType": ("machines/types.csv", P(("makerspace",), include_global_if_unowned=True)),
    "machines.MachineUsageEntry": ("machines/usage_entries.csv", P(("machine__makerspace",))),
    "machines.MakerspaceMachineTypePricing": ("machines/type_pricing.csv", P(("makerspace",), ("machine_type__makerspace",))),
    "machines.RoleMachineScope": ("members/role_machine_scopes.csv", P(("role__makerspace",), ("machine__makerspace",))),
    "machines.RoleMachineTypeScope": ("members/role_machine_type_scopes.csv", P(("role__makerspace",), ("machine_type__makerspace",))),
    "machines.ServiceBucket": ("machine_service/buckets.csv", P(("machine__makerspace",))),
    "machines.ServiceQueue": ("machine_service/queues.csv", P(("makerspace",), ("machine_type__makerspace",))),
    "machines.ServiceRequestConsumption": ("machine_service/request_consumptions.csv", P(("service_request__makerspace",), ("machine_consumable__machine__makerspace",))),
    "machines.ServiceRequestFile": ("machine_service/files.csv", P(("makerspace",))),
    "maintenance.MaintenanceLog": ("maintenance/logs.csv", P(("machine__makerspace",))),
    "maintenance.MaintenanceLogDocument": ("maintenance/documents.csv", P(("log__machine__makerspace",))),
    "maintenance.MaintenanceSchedule": ("maintenance/schedules.csv", P(("machine__makerspace",))),
    "makerspaces.Makerspace": ("makerspace/config.csv", P(("pk",))),
    "makerspaces.MakerspaceMembership": ("members/roster.csv", P(("makerspace",))),
    "makerspaces.MakerspaceRole": ("members/roles.csv", P(("makerspace",))),
    "makerspaces.MakerspaceWaiver": ("members/waivers.csv", P(("makerspace",))),
    "makerspaces.MemberProfile": ("members/profiles.csv", P(("membership__makerspace",))),
    "makerspaces.MemberProject": ("members/projects.csv", P(("profile__membership__makerspace",))),
    "makerspaces.MembershipRequest": ("members/membership_requests.csv", P(("makerspace",))),
    "notifications.Notification": ("notifications/inbox.csv", P(("makerspace",))),
    "operations.InventoryAdjustment": ("operations/inventory_adjustments.csv", P(("makerspace",))),
    "operations.QrPrintBatch": ("operations/qr_print_batches.csv", P(("makerspace",))),
    "operations.QrPrintBatchItem": ("operations/qr_print_batch_items.csv", P(("batch__makerspace",))),
    "operations.StocktakeLedgerEntry": ("stocktake/ledger.csv", P(("makerspace",), ("stocktake__makerspace",))),
    "operations.StocktakeLine": ("stocktake/lines.csv", P(("stocktake__makerspace",), ("product__makerspace", "asset__makerspace", "container__makerspace"))),
    "operations.StocktakeSession": ("stocktake/sessions.csv", P(("makerspace",), ("container__makerspace",))),
    "operations.StockTransfer": ("transfers/transfers.csv", P(("makerspace", "source_makerspace", "destination_makerspace"))),
    "operations.StockTransferLine": ("transfers/lines.csv", P(("transfer__makerspace", "transfer__source_makerspace", "transfer__destination_makerspace"))),
    "payments.MakerspacePaymentSettings": ("makerspace/payment_settings.csv", P(("makerspace",))),
    "payments.Payment": ("payments/payments.csv", P(("makerspace",))),
    "presence.PresenceSession": ("presence/sessions.csv", P(("makerspace",), ("membership__makerspace",))),
    "procurement.ToBuyItem": ("procurement/to_buy_items.csv", P(("makerspace",))),
    "procurement.ToBuyReceipt": ("procurement/receipts.csv", P(("to_buy_item__makerspace",))),
    "warranty.Warranty": ("warranty/warranties.csv", P(("makerspace",), ("asset__makerspace", "machine__makerspace"))),
    "warranty.WarrantyDocument": ("warranty/documents.csv", P(("warranty__makerspace",))),
}


def _columns(fidelity, label):
    model = apps.get_model(label)
    columns = []
    omissions = {}
    for field in model._meta.get_fields():
        disposition = FIELDS.get((fidelity, label, field.name))
        if disposition is None:
            continue
        if isinstance(disposition, Omitted):
            omissions[field.name] = disposition.reason
            continue
        columns.append(Column(field.attname, (field.name,), disposition))
    if label == "audit.AuditLog":
        columns.append(
            Column(
                "actor_username",
                ("actor__username",),
                Transformed("Intentional identifying disclosure for a referenced audit actor."),
            )
        )
    return tuple(columns), omissions


DATASETS = {}
for _fidelity in Fidelity:
    for _label, (_path, _predicate) in DATASET_SPECS.items():
        _columns_for_dataset, _omissions = _columns(_fidelity, _label)
        DATASETS[(_fidelity, _path)] = Dataset(
            fidelity=_fidelity,
            path=_path,
            model=_label,
            predicate=_predicate,
            keyset=("id",),
            columns=_columns_for_dataset,
            explicit_omissions=_omissions,
        )

# Global users are selected by USER_EDGES rather than a tenant FK predicate.
for _fidelity in Fidelity:
    _columns_for_dataset, _omissions = _columns(_fidelity, "accounts.User")
    DATASETS[(_fidelity, "global/users.csv")] = Dataset(
        fidelity=_fidelity,
        path="global/users.csv",
        model="accounts.User",
        predicate=P(("closure",)),
        keyset=("id",),
        columns=_columns_for_dataset,
        explicit_omissions=_omissions,
    )

assert EXPORTED_MODELS == frozenset(DATASET_SPECS)
