"""Independent scratch/target verification for D6 cross-tenant rows."""

from django.apps import apps
from django.db.models import Q

from .tenant_dump_cross_tenant import _loss_key, validate_cross_tenant_registry
from .tenant_dump_cross_tenant_rules import (
    LOST_EDGE_REASON_CODES,
    PAYMENT_CLEARED_VALUES,
    TERMINAL_PAYMENT_STATUSES,
)
from .tenant_dump_errors import TenantDumpVerificationError


def verify_cross_tenant_projection(using, makerspace_id):
    validate_cross_tenant_registry()
    if apps.get_model("events.EventCollaborator")._base_manager.using(using).exists():
        raise TenantDumpVerificationError("A foreign EventCollaborator survived D6.")
    Registration = apps.get_model("events.EventRegistration")
    if Registration._base_manager.using(using).filter(
        Q(registered_via_makerspace_id__isnull=False)
        | Q(payment_via_makerspace_id__isnull=False)
    ).exists():
        raise TenantDumpVerificationError("Event registration routing survived D6.")
    Payment = apps.get_model("payments.Payment")
    for row in Payment._base_manager.using(using).values(
        "status", *PAYMENT_CLEARED_VALUES
    ):
        if row["status"] not in TERMINAL_PAYMENT_STATUSES or any(
            row[name] != value for name, value in PAYMENT_CLEARED_VALUES.items()
        ):
            raise TenantDumpVerificationError(
                "A payment violates the terminal-history projection."
            )
    _verify_transfers(using, int(makerspace_id))
    return True


def verify_lost_edge_manifest(value):
    keys = {"model_label", "source_row_pk", "field_name", "reason_code"}
    decisions = (
        [
            (
                item.get("model_label"),
                item.get("field_name"),
                item.get("reason_code"),
            )
            if isinstance(item, dict)
            else None
            for item in value
        ]
        if isinstance(value, list)
        else []
    )
    if (
        not isinstance(value, list)
        or any(not isinstance(item, dict) or set(item) != keys for item in value)
        or any(
            type(item["source_row_pk"]) is not int
            or item["source_row_pk"] <= 0
            for item in value
        )
        or any(decision not in LOST_EDGE_REASON_CODES for decision in decisions)
        or len({_loss_key(item) for item in value}) != len(value)
        or value != sorted(value, key=_loss_key)
    ):
        raise TenantDumpVerificationError(
            "The cross-tenant lost-edge manifest is invalid."
        )
    return True


def _verify_transfers(using, makerspace_id):
    Transfer = apps.get_model("operations.StockTransfer")
    for row in Transfer._base_manager.using(using).values(
        "makerspace_id",
        "source_makerspace_id",
        "source_container__makerspace_id",
        "destination_makerspace_id",
        "destination_container__makerspace_id",
    ):
        if row["makerspace_id"] != makerspace_id:
            raise TenantDumpVerificationError(
                "A foreign-owned StockTransfer survived D6."
            )
        for prefix in ("source", "destination"):
            space = row[f"{prefix}_makerspace_id"]
            container = row[f"{prefix}_container__makerspace_id"]
            if space not in (None, makerspace_id) or container not in (
                None, makerspace_id
            ):
                raise TenantDumpVerificationError(
                    "A StockTransfer foreign pair survived D6."
                )
            if space is None and container is not None:
                raise TenantDumpVerificationError(
                    "A StockTransfer pair was not nulled together."
                )
