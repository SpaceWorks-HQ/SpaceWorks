"""Declared handling for deployment-global uniqueness during materialization."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Callable


class UniqueValueDisposition(StrEnum):
    DROP_ROW = "drop_row"
    OMITTED_FRESH = "omitted_fresh"
    OMITTED_NULL = "omitted_null"
    PRESERVE_OR_REGENERATE = "preserve_or_regenerate"
    REMAPPED_REFERENCE = "remapped_reference"
    SEEDED_RESOLUTION = "seeded_resolution"
    TARGET_CREATION = "target_creation"


ValueGenerator = Callable[[dict, object, object], object]


@dataclass(frozen=True)
class UniqueValuePolicy:
    disposition: UniqueValueDisposition
    reason: str
    collision_field: str | None = None
    generator: ValueGenerator | None = None


def _policy(disposition, reason, *, field=None, generator=None):
    return UniqueValuePolicy(disposition, reason, field, generator)


def _extension(value):
    suffix = PurePosixPath(str(value)).name
    return suffix.rsplit(".", 1)[1] if "." in suffix else ""


def _evidence_key(row, target, _source_value):
    from apps.evidence.storage import evidence_object_key

    return evidence_object_key(target.pk, row["evidence_type"])


def _machine_document_key(row, target, source_value):
    from apps.machines.storage import machine_object_key

    return machine_object_key(target.pk, _extension(source_value))


def _service_file_key(row, target, _source_value):
    from apps.machines.service_storage import service_object_key

    context = row.get("service_request_id") or row.get("queue_id") or row["id"]
    return service_object_key(target.pk, context)


def _maintenance_document_key(row, target, source_value):
    from apps.maintenance.models import MaintenanceLog
    from apps.maintenance.storage import log_document_object_key

    machine_id = MaintenanceLog.objects.values_list("machine_id", flat=True).get(
        pk=row["log_id"]
    )
    return log_document_object_key(target.pk, machine_id, _extension(source_value))


def _receipt_key(row, target, source_value):
    from apps.procurement.storage import receipt_object_key

    return receipt_object_key(target.pk, _extension(source_value))


def _warranty_document_key(row, target, source_value):
    from apps.warranty.storage import warranty_object_key

    return warranty_object_key(target.pk, _extension(source_value))


FRESH = UniqueValueDisposition.OMITTED_FRESH
NULL = UniqueValueDisposition.OMITTED_NULL
PRESERVE = UniqueValueDisposition.PRESERVE_OR_REGENERATE
REMAP = UniqueValueDisposition.REMAPPED_REFERENCE


# Keys are (model label, metadata rule name). Field-level rules use ``field:<name>``;
# named constraints retain their database name. Every entry is intentionally literal:
# adding a new global uniqueness rule must force a reviewed migration disposition.
DEPLOYMENT_GLOBAL_UNIQUE_RULES = {
    ("apiclients.ApiClient", "field:client_id"): _policy(
        UniqueValueDisposition.DROP_ROW,
        "API clients are dropped with their omitted credentials.",
    ),
    ("audit.AuditLog", "field:event_uuid"): _policy(
        NULL,
        "Audit integrity identity is omitted; the target reseals its own rows.",
    ),
    ("bookings.BookableSpace", "field:public_token"): _policy(
        FRESH, "Source bearer tokens are replaced."
    ),
    ("bookings.Booking", "field:public_token"): _policy(
        FRESH, "Source bearer tokens are replaced."
    ),
    ("boxes.Box", "field:code"): _policy(
        PRESERVE,
        "Keep printed box labels unless the target already uses the code.",
        field="code",
    ),
    ("boxes.QrCode", "field:payload"): _policy(
        PRESERVE,
        "Keep printed QR labels unless the target already uses the payload.",
        field="payload",
    ),
    ("events.Event", "field:public_token"): _policy(
        FRESH, "Source bearer tokens are replaced."
    ),
    ("events.EventRegistration", "field:checkin_token"): _policy(
        FRESH, "Source check-in credentials are replaced."
    ),
    ("evidence.EvidencePhoto", "field:object_key"): _policy(
        PRESERVE,
        "Keep the archived evidence key unless it already names a target object.",
        field="object_key",
        generator=_evidence_key,
    ),
    ("hardware_requests.HardwareRequest", "uniq_active_loan_per_box"): _policy(
        REMAP, "The box reference is remapped to the imported box."
    ),
    ("hardware_requests.HardwareRequest", "field:issue_evidence"): _policy(
        REMAP, "The one-to-one evidence reference is remapped."
    ),
    ("hardware_requests.HardwareRequest", "field:public_token"): _policy(
        FRESH, "Source bearer tokens are replaced."
    ),
    (
        "hardware_requests.PublicToolLoan",
        "uniq_active_loan_per_container",
    ): _policy(REMAP, "The container reference is remapped."),
    (
        "hardware_requests.PublicToolLoan",
        "uniq_active_public_tool_loan_per_qr",
    ): _policy(REMAP, "The QR reference is remapped."),
    ("hardware_requests.PublicToolLoan", "field:request"): _policy(
        REMAP, "The one-to-one request reference is remapped."
    ),
    ("hardware_requests.PublicToolLoan", "field:return_evidence"): _policy(
        REMAP, "The one-to-one evidence reference is remapped."
    ),
    ("hardware_requests.ReturnEvent", "field:evidence"): _policy(
        REMAP, "The one-to-one evidence reference is remapped."
    ),
    ("machines.Machine", "field:legacy_print_printer_id"): _policy(
        NULL, "Retired cutover provenance is omitted and reconstructed as NULL."
    ),
    (
        "machines.MachineConsumableAdjustment",
        "field:legacy_filament_adjustment_id",
    ): _policy(
        NULL, "Retired cutover provenance is omitted and reconstructed as NULL."
    ),
    (
        "machines.MachineConsumablePool",
        "field:legacy_filament_spool_id",
    ): _policy(
        NULL, "Retired cutover provenance is omitted and reconstructed as NULL."
    ),
    ("machines.MachineDocument", "field:object_key"): _policy(
        PRESERVE,
        "Keep the archived document key unless it collides on the target.",
        field="object_key",
        generator=_machine_document_key,
    ),
    ("machines.MachineServiceRequest", "field:legacy_print_request_id"): _policy(
        NULL, "Retired cutover provenance is omitted and reconstructed as NULL."
    ),
    ("machines.MachineServiceRequest", "field:public_token"): _policy(
        FRESH, "Source bearer tokens are replaced."
    ),
    ("machines.MachineType", "uniq_global_machinetype_slug"): _policy(
        UniqueValueDisposition.SEEDED_RESOLUTION,
        "Global built-ins resolve only after their definition fingerprint matches.",
    ),
    ("machines.MachineUsageEntry", "field:legacy_manual_print_log_id"): _policy(
        NULL, "Retired cutover provenance is omitted and reconstructed as NULL."
    ),
    ("machines.ServiceQueue", "field:legacy_print_bucket_id"): _policy(
        NULL, "Retired cutover provenance is omitted and reconstructed as NULL."
    ),
    (
        "machines.ServiceRequestFile",
        "field:legacy_print_request_file_id",
    ): _policy(
        NULL, "Retired cutover provenance is omitted and reconstructed as NULL."
    ),
    ("machines.ServiceRequestFile", "field:object_key"): _policy(
        PRESERVE,
        "Keep the archived service-file key unless it collides on the target.",
        field="object_key",
        generator=_service_file_key,
    ),
    ("maintenance.MaintenanceLogDocument", "field:object_key"): _policy(
        PRESERVE,
        "Keep the archived maintenance-document key unless it collides on the target.",
        field="object_key",
        generator=_maintenance_document_key,
    ),
    ("makerspaces.Makerspace", "field:public_code"): _policy(
        UniqueValueDisposition.TARGET_CREATION,
        "Target creation preserves or regenerates the public code.",
    ),
    ("makerspaces.Makerspace", "field:slug"): _policy(
        UniqueValueDisposition.TARGET_CREATION,
        "Target creation selects an available slug.",
    ),
    (
        "makerspaces.Makerspace",
        "uniq_makerspace_frontend_domain_ci",
    ): _policy(
        UniqueValueDisposition.TARGET_CREATION,
        "Target creation clears source routing authority.",
    ),
    ("makerspaces.Makerspace", "uniq_makerspace_public_api_key"): _policy(
        UniqueValueDisposition.TARGET_CREATION,
        "Target creation issues a fresh public API key.",
    ),
    (
        "payments.MakerspacePaymentSettings",
        "field:connect_account_id",
    ): _policy(
        NULL, "Source provider bindings are omitted and reconstructed as NULL."
    ),
    ("payments.Payment", "field:stripe_checkout_session_id"): _policy(
        NULL, "Source provider identifiers are omitted and reconstructed as NULL."
    ),
    ("payments.Payment", "field:stripe_payment_intent_id"): _policy(
        NULL, "Source provider identifiers are omitted and reconstructed as NULL."
    ),
    (
        "payments.Payment",
        "payment_external_order_once_per_provider",
    ): _policy(
        NULL, "The omitted external_order_id makes this target constraint inert."
    ),
    (
        "payments.Payment",
        "payment_external_payment_once_per_provider",
    ): _policy(
        NULL, "The omitted external_payment_id makes this target constraint inert."
    ),
    ("procurement.ToBuyReceipt", "field:object_key"): _policy(
        PRESERVE,
        "Keep the archived receipt key unless it collides on the target.",
        field="object_key",
        generator=_receipt_key,
    ),
    ("warranty.WarrantyDocument", "field:object_key"): _policy(
        PRESERVE,
        "Keep the archived warranty-document key unless it collides on the target.",
        field="object_key",
        generator=_warranty_document_key,
    ),
}


def collision_policy(model_label, field_name):
    policy = DEPLOYMENT_GLOBAL_UNIQUE_RULES.get((model_label, f"field:{field_name}"))
    if policy and policy.disposition is PRESERVE:
        return policy
    return None
