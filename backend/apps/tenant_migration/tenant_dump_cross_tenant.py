"""Exact D6 cross-tenant and payment row/field dispositions."""

from dataclasses import dataclass

from django.apps import apps
from django.db.models import Q

from apps.data_export.fields import EXTERNAL_REFERENCES

from .tenant_dump_errors import (
    TenantDumpDispositionRefused,
)
from .tenant_dump_cross_tenant_rules import (
    CROSS_TENANT_EDGE_RULES,
    PAYMENT_CLEARED_VALUES,
    TERMINAL_PAYMENT_STATUSES,
    CrossTenantDisposition,
)


@dataclass(frozen=True)
class CrossTenantSourceFacts:
    lost_edges: tuple[dict, ...]
    dropped_transfer_line_ids: frozenset[int]
    nulled_transfer_pairs: frozenset[tuple[int, str]]


def inspect_cross_tenant_source(makerspace_id, *, using="default"):
    """Read cross-tenant facts only from the immutable source database image."""
    validate_cross_tenant_registry()
    makerspace_id = int(makerspace_id)
    losses = []

    Collaborator = apps.get_model("events.EventCollaborator")
    collaborators = Collaborator._base_manager.using(using).filter(
        Q(event__makerspace_id=makerspace_id) | Q(makerspace_id=makerspace_id)
    ).values("id", "event__makerspace_id", "makerspace_id")
    for row in collaborators:
        if row["event__makerspace_id"] == makerspace_id != row["makerspace_id"]:
            field = "makerspace"
        elif row["makerspace_id"] == makerspace_id != row["event__makerspace_id"]:
            field = "event"
        else:
            continue
        losses.append(
            _loss(
                "events.EventCollaborator",
                row["id"],
                field,
                "foreign_collaborator_dropped",
            )
        )

    Transfer = apps.get_model("operations.StockTransfer")
    transfers = Transfer._base_manager.using(using).filter(
        Q(makerspace_id=makerspace_id)
        | Q(source_makerspace_id=makerspace_id)
        | Q(destination_makerspace_id=makerspace_id)
    ).values(
        "id", "makerspace_id",
        "source_makerspace_id", "source_container_id",
        "source_container__makerspace_id",
        "destination_makerspace_id", "destination_container_id",
        "destination_container__makerspace_id",
    )
    foreign_transfer_ids = set()
    nulled_pairs = set()
    for row in transfers:
        if row["makerspace_id"] != makerspace_id:
            foreign_transfer_ids.add(row["id"])
            losses.append(
                _loss(
                    "operations.StockTransfer",
                    row["id"],
                    "makerspace",
                    "foreign_owned_transfer_dropped",
                )
            )
            continue
        for field in ("source_makerspace", "destination_makerspace"):
            prefix = field.removesuffix("_makerspace")
            value = row[f"{field}_id"]
            container_id = row[f"{prefix}_container_id"]
            container_owner = row[f"{prefix}_container__makerspace_id"]
            if value not in (None, makerspace_id) or container_owner not in (
                None, makerspace_id
            ):
                nulled_pairs.add((row["id"], prefix))
            if value not in (None, makerspace_id):
                losses.append(
                    _loss(
                        "operations.StockTransfer",
                        row["id"],
                        field,
                        "foreign_counterparty_nulled",
                    )
                )
            if container_id is not None and container_owner != makerspace_id:
                losses.append(
                    _loss(
                        "operations.StockTransfer",
                        row["id"],
                        f"{prefix}_container",
                        "foreign_counterparty_container_nulled",
                    )
                )

    Line = apps.get_model("operations.StockTransferLine")
    dropped_lines = set()
    lines = Line._base_manager.using(using).filter(
        Q(transfer_id__in=foreign_transfer_ids) | Q(transfer__makerspace_id=makerspace_id)
    ).values(
        "id", "transfer_id", "transfer__makerspace_id",
        "product__makerspace_id", "asset__makerspace_id",
    )
    for row in lines:
        owner = row["transfer__makerspace_id"]
        product_owner = row["product__makerspace_id"]
        asset_owner = row["asset__makerspace_id"]
        if owner != makerspace_id or any(
            value not in (None, makerspace_id) for value in (product_owner, asset_owner)
        ):
            dropped_lines.add(row["id"])
            losses.append(
                _loss(
                    "operations.StockTransferLine",
                    row["id"],
                    "transfer",
                    "foreign_owned_transfer_line_dropped",
                )
            )

    Payment = apps.get_model("payments.Payment")
    for row in Payment._base_manager.using(using).filter(
        makerspace_id=makerspace_id
    ).values("id", "status"):
        if row["status"] == "pending":
            raise TenantDumpDispositionRefused(
                f"Pending Payment {row['id']} is an unresolved obligation.",
                reason_code="pending_payment",
            )
        if row["status"] not in TERMINAL_PAYMENT_STATUSES:
            raise TenantDumpDispositionRefused(
                f"Payment {row['id']} has an unclassified status.",
                reason_code="unclassified_payment_status",
            )
    return CrossTenantSourceFacts(
        tuple(sorted(losses, key=_loss_key)),
        frozenset(dropped_lines),
        frozenset(nulled_pairs),
    )


def validate_cross_tenant_registry(rules=CROSS_TENANT_EDGE_RULES):
    if set(rules) != set(EXTERNAL_REFERENCES):
        raise TenantDumpDispositionRefused(
            "The cross-tenant FK registry has an unclassified edge.",
            reason_code="unclassified_cross_tenant_edge",
        )
    for (label, field_name), rule in rules.items():
        field = apps.get_model(label)._meta.get_field(field_name)
        if not field.concrete or not field.is_relation or not rule.reason:
            raise TenantDumpDispositionRefused(
                f"Cross-tenant rule {label}.{field_name} is invalid.",
                reason_code="invalid_cross_tenant_edge",
            )
        if rule.disposition is not CrossTenantDisposition.DROP_ROW and not field.null:
            raise TenantDumpDispositionRefused(
                f"Cross-tenant rule {label}.{field_name} cannot legally null.",
                reason_code="non_nullable_cross_tenant_edge",
            )
    return True


def project_cross_tenant_values(model, values, source, makerspace_id):
    """Apply the paired StockTransfer null rule to one already-sanitized row."""
    if model._meta.label != "operations.StockTransfer":
        return values
    projected = dict(values)
    for makerspace_field, container_field in (
        ("source_makerspace", "source_container"),
        ("destination_makerspace", "destination_container"),
    ):
        field = model._meta.get_field(makerspace_field)
        prefix = makerspace_field.removesuffix("_makerspace")
        if source.get(f"_d6_null_{prefix}_pair") or source.get(
            field.attname
        ) not in (None, int(makerspace_id)):
            projected[field.column] = None
            projected[model._meta.get_field(container_field).column] = None
    return projected


def _loss(model_label, source_row_pk, field_name, reason_code):
    return {
        "model_label": model_label,
        "source_row_pk": source_row_pk,
        "field_name": field_name,
        "reason_code": reason_code,
    }


def _loss_key(item):
    fields = ("model_label", "source_row_pk", "field_name", "reason_code")
    return tuple(str(item[name]) for name in fields)
