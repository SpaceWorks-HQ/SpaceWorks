"""Committed D6 edge, payment, and lost-edge policy vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class CrossTenantDisposition(StrEnum):
    DROP_ROW = "drop_row"
    NULL = "null"
    NULL_WITH_PAIRED_CONTAINER = "null_with_paired_container"
    CLEAR_TERMINAL_PROVIDER_BINDING = "clear_terminal_provider_binding"


@dataclass(frozen=True)
class CrossTenantRule:
    disposition: CrossTenantDisposition
    reason: str


CROSS_TENANT_EDGE_RULES = {
    ("events.EventCollaborator", "event"): CrossTenantRule(
        CrossTenantDisposition.DROP_ROW, "A foreign-hosted collaboration is dropped."
    ),
    ("events.EventCollaborator", "makerspace"): CrossTenantRule(
        CrossTenantDisposition.DROP_ROW, "A foreign collaborator grant is dropped."
    ),
    ("operations.StockTransfer", "source_makerspace"): CrossTenantRule(
        CrossTenantDisposition.NULL_WITH_PAIRED_CONTAINER,
        "A foreign source and its source container are nulled together.",
    ),
    ("operations.StockTransfer", "destination_makerspace"): CrossTenantRule(
        CrossTenantDisposition.NULL_WITH_PAIRED_CONTAINER,
        "A foreign destination and its destination container are nulled together.",
    ),
    ("operations.StockTransfer", "source_container"): CrossTenantRule(
        CrossTenantDisposition.NULL_WITH_PAIRED_CONTAINER,
        "The source container follows its foreign makerspace disposition.",
    ),
    ("operations.StockTransfer", "destination_container"): CrossTenantRule(
        CrossTenantDisposition.NULL_WITH_PAIRED_CONTAINER,
        "The destination container follows its foreign makerspace disposition.",
    ),
    ("events.EventRegistration", "registered_via_makerspace"): CrossTenantRule(
        CrossTenantDisposition.NULL, "Source registration routing does not travel."
    ),
    ("events.EventRegistration", "payment_via_makerspace"): CrossTenantRule(
        CrossTenantDisposition.NULL, "Terminal foreign payment routing does not travel."
    ),
    ("payments.Payment", "via_makerspace"): CrossTenantRule(
        CrossTenantDisposition.CLEAR_TERMINAL_PROVIDER_BINDING,
        "Terminal payment routing and live provider handles are cleared.",
    ),
}

TERMINAL_PAYMENT_STATUSES = frozenset(
    {"paid_online", "paid_offline", "waived", "canceled"}
)
PAYMENT_CLEARED_VALUES = {
    "via_makerspace_id": None,
    "external_order_id": None,
    "external_payment_id": None,
    "checkout_url": "",
    "stripe_provider": "raw",
    "stripe_connected_account_id": None,
    "stripe_application_fee_amount": 0,
    "online_rail": None,
    "stripe_checkout_session_id": None,
    "stripe_checkout_url": "",
    "stripe_checkout_session_expired_at": None,
    "stripe_payment_intent_id": None,
}
LOST_EDGE_REASON_CODES = frozenset(
    {
        ("events.EventCollaborator", "event", "foreign_collaborator_dropped"),
        ("events.EventCollaborator", "makerspace", "foreign_collaborator_dropped"),
        ("operations.StockTransfer", "makerspace", "foreign_owned_transfer_dropped"),
        ("operations.StockTransfer", "source_makerspace", "foreign_counterparty_nulled"),
        ("operations.StockTransfer", "destination_makerspace", "foreign_counterparty_nulled"),
        ("operations.StockTransfer", "source_container", "foreign_counterparty_container_nulled"),
        (
            "operations.StockTransfer",
            "destination_container",
            "foreign_counterparty_container_nulled",
        ),
        ("operations.StockTransferLine", "transfer", "foreign_owned_transfer_line_dropped"),
    }
)
