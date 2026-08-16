"""Import dispositions for references that Django cannot remap by itself."""

from dataclasses import dataclass

from .audit_references import (
    AUDIT_META_REFERENCES,
    AUDIT_TARGET_DISPOSITIONS,
    UNRECOGNISED_AUDIT_TARGET,
    normalize_audit_target_type,
)


@dataclass(frozen=True)
class RemapScalar:
    target_model_label: str


@dataclass(frozen=True)
class NullWithProvenance:
    target_model_label: str
    kind: str


@dataclass(frozen=True)
class EmbeddedRoute:
    pattern: str
    target_model_label: str


@dataclass(frozen=True)
class ClearWithProvenance:
    kind: str


DISCRIMINATOR_REFERENCES = {
    ("boxes.QrCode", "target_type", "target_id"): {
        "box": "boxes.Box",
        "product": "inventory.InventoryProduct",
        "asset": "inventory.InventoryAsset",
    },
    ("hardware_requests.PublicToolLoan", "target_type", "target_id"): {
        "box": "boxes.Box",
        "product": "inventory.InventoryProduct",
        "asset": "inventory.InventoryAsset",
        # Direct handouts point at the request created for that handover. This value
        # cannot share the QR discriminator map used by self-checkout loans.
        "direct": "hardware_requests.HardwareRequest",
    },
    ("operations.QrPrintBatchItem", "target_type", "target_id"): {
        # A batch item is an immutable-at-print-time snapshot. Remap its archived
        # pair, never the current qr_code pair: rebinding a QR intentionally leaves
        # old batch items and their physical-label text describing the old target.
        "box": "boxes.Box",
        "product": "inventory.InventoryProduct",
        "asset": "inventory.InventoryAsset",
    },
}

RAW_SCALAR_REFERENCES = {
    ("machines.ServiceRequestFile", "owner_user_id"): RemapScalar("accounts.User"),
}

OMITTED_TARGET_RELATIONS = {
    (
        "presence.PresenceSession",
        "created_via_claim_session",
    ): NullWithProvenance(
        "accounts.MemberClaimCode",
        "omitted_target_model",
    ),
}

PAYMENT_SUBJECT_REFERENCES = {
    "machine_service_request": "machines.MachineServiceRequest",
    "booking": "bookings.Booking",
    "event_registration": "events.EventRegistration",
    "makerspace_membership": "makerspaces.MakerspaceMembership",
}

NOTIFICATION_URL_ROUTES = (
    EmbeddedRoute(
        pattern=r"\A/admin/machine-service/requests/(?P<object_id>[1-9][0-9]*)\Z",
        target_model_label="machines.MachineServiceRequest",
    ),
)

UNRECOGNISED_NOTIFICATION_URL = ClearWithProvenance(
    "unrecognised_notification_url"
)
ORPHANED_PAYMENT_SUBJECT_KIND = "orphaned_payment_subject"
