"""Declared handling for deployment-global uniqueness during materialization."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from .unique_value_generators import (
    certificate_key as _certificate_key,
    evidence_key as _evidence_key,
    machine_document_key as _machine_document_key,
    maintenance_document_key as _maintenance_document_key,
    receipt_key as _receipt_key,
    refuse_certificate_serial_collision as _refuse_certificate_serial_collision,
    refuse_checkin_operation_collision as _refuse_checkin_operation_collision,
    service_file_key as _service_file_key,
    warranty_document_key as _warranty_document_key,
)

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
    ("apiclients.ApiClient", "field:import_provenance_digest"): _policy(
        UniqueValueDisposition.DROP_ROW,
        "Source API clients are dropped; target reissuance creates fresh provenance.",
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
    ("events.Event", "field:calendar_uid"): _policy(
        PRESERVE,
        "Keep stable calendar identity unless the target already uses it.",
        field="calendar_uid",
    ),
    ("events.EventSeries", "field:public_token"): _policy(
        FRESH, "Source series bearer tokens are replaced."
    ),
    ("events.EventSeries", "field:calendar_uid"): _policy(
        PRESERVE,
        "Keep stable series calendar identity unless the target already uses it.",
        field="calendar_uid",
    ),
    ("events.Event", "uniq_event_series_occurrence_key"): _policy(
        REMAP, "The series reference is remapped with its occurrence identity."
    ),
    ("events.EventRegistration", "field:checkin_token"): _policy(
        FRESH, "Source check-in credentials are replaced."
    ),
    ("events.EventCheckInEvent", "field:operation_id"): _policy(
        PRESERVE,
        "Preserve immutable synchronization identity; refuse a target collision.",
        field="operation_id",
        generator=_refuse_checkin_operation_collision,
    ),
    ("events.EventAttendanceCertificate", "field:serial"): _policy(
        PRESERVE,
        "Preserve the serial printed inside the immutable PDF; refuse a collision.",
        field="serial",
        generator=_refuse_certificate_serial_collision,
    ),
    ("events.EventAttendanceCertificate", "field:object_key"): _policy(
        PRESERVE,
        "Keep the archived private certificate key unless it collides on the target.",
        field="object_key",
        generator=_certificate_key,
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
    ("makerspaces.Makerspace", "field:anonymous_requester"): _policy(
        NULL,
        "The anonymous-request principal is a per-deployment system row, not a person: "
        "the target creates its own lazily on the first account-less request, so importing "
        "the source's would carry an inert User the target must never resolve to a human.",
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
