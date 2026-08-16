"""AuditLog reference declarations used by PORTABLE tenant archives.

Audit metadata uses ``source:<value>`` for source-local identifiers.  That prefix is
deliberately not a valid live primary key representation, including when an identifier
is stored as a JSON dictionary key.
"""

from dataclasses import dataclass
from enum import StrEnum

from apps.data_export.models import MODELS
from apps.data_export.types import Exported, GlobalReference, OmittedModel


SOURCE_ID_PREFIX = "source:"


class AuditReferenceDisposition(StrEnum):
    REMAP = "remap"
    NULL = "null"
    SOURCE_LOCAL_SNAPSHOT = "source_local_snapshot"


@dataclass(frozen=True)
class AuditReference:
    disposition: AuditReferenceDisposition
    target_model_label: str | None
    kind: str = ""


def normalize_audit_target_type(model_label: str) -> str:
    """Return the exact lowercase label written by ``audit.services.record``."""
    app_label, separator, model_name = str(model_label).partition(".")
    if not separator or not app_label or not model_name:
        return str(model_label).lower()
    return f"{app_label.lower()}.{model_name.lower()}"


def audit_target_dispositions(models=MODELS):
    """Derive recognised audit targets from the total export model registry."""
    dispositions = {}
    for label, model_disposition in models.items():
        key = normalize_audit_target_type(label)
        if isinstance(model_disposition, Exported):
            dispositions[key] = AuditReference(
                AuditReferenceDisposition.REMAP, label
            )
        elif isinstance(model_disposition, GlobalReference):
            dispositions[key] = AuditReference(
                AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT,
                label,
                "audit_user_target" if label == "accounts.User" else "audit_global_target",
            )
        elif isinstance(model_disposition, OmittedModel):
            dispositions[key] = AuditReference(
                AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT,
                label,
                "audit_omitted_target_model",
            )
    return dispositions


AUDIT_TARGET_DISPOSITIONS = audit_target_dispositions()
UNRECOGNISED_AUDIT_TARGET = AuditReference(
    AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT,
    None,
    "audit_unrecognised_or_dropped_target",
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
    ("encryption.write_fence_closed", "operation_id"),
    ("encryption.write_fence_opened", "operation_id"),
    ("payment.checkout_created", "subject_id"),
    ("payment.created", "subject_id"),
    ("payment.paid_after_terminal", "event_id"),
    ("payment.paid_online", "event_id"),
    ("payments.connect_authorization_revoked", "connect_account_id"),
    ("payments.connect_previous_authorization_revoked", "connect_account_id"),
    ("procurement.moved_to_printing", "result_id"),
    ("qr.rebound", "new_target_id"),
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
