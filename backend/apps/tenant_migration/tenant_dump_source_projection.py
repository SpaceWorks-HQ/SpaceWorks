"""Key-free source-row projection for one Lane D makerspace."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from types import MappingProxyType

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection

from apps.backup.raw_projection import no_decrypt_guard, raw_records
from apps.data_export.datasets import DATASET_SPECS
from apps.data_export.references import USER_EDGES
from apps.data_export.types import Fidelity

from .tenant_dump_catalog import validate_catalog, validate_unowned_tables
from .tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from .tenant_dump_types import ModelDisposition


class TenantDumpProjectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TenantDumpSourceProjection:
    makerspace_id: int
    rows: Mapping[str, tuple[dict, ...]]
    machine_operator_manifest: tuple[dict, ...]


def project_makerspace_source(makerspace_id):
    """Read one tenant with the shared raw producer, then prove live-grant closure."""
    validate_catalog()
    validate_unowned_tables(connection.introspection.table_names())
    projected = {}
    with no_decrypt_guard():
        for label, (_path, predicate) in sorted(DATASET_SPECS.items()):
            rule = FIRST_PARTY_MODEL_RULES[label]
            if rule.disposition is ModelDisposition.DROP:
                continue
            model = apps.get_model(label)
            queryset = model._default_manager.filter(
                predicate.as_q(makerspace_id)
            ).order_by(model._meta.pk.name)
            records = raw_records(queryset, model)
            projected[label] = tuple(
                row
                for row in records
                if _source_row_allowed(label, row, makerspace_id)
            )

        _close_conditional_rows(projected)
        user_ids = _referenced_user_ids(projected)
        User = apps.get_model("accounts.User")
        projected["accounts.User"] = tuple(
            raw_records(
                User._default_manager.filter(pk__in=user_ids).order_by(
                    User._meta.pk.name
                ),
                User,
            )
        )
        manifest = validate_machine_operator_closure(projected, makerspace_id)

    return TenantDumpSourceProjection(
        makerspace_id=makerspace_id,
        rows=MappingProxyType(projected),
        machine_operator_manifest=manifest,
    )


def _source_row_allowed(label, row, makerspace_id):
    if label == "makerspaces.MembershipRequest":
        return row["state"] not in {"requested", "invited"}
    if label == "apiclients.ApiKeyRequest":
        return row["status"] != "pending"
    if label == "payments.Payment" and row["status"] == "pending":
        raise TenantDumpProjectionError(
            f"pending Payment {row['id']} is an unresolved obligation"
        )
    if label == "integrations.NotificationDestination":
        return row["channel"] == "telegram"
    if label == "operations.StockTransfer":
        return row["makerspace_id"] == makerspace_id
    if label == "operations.StockTransferLine":
        return row["_transfer_makerspace_id"] == makerspace_id
    return True


def _close_conditional_rows(rows):
    kept_destinations = {
        row["id"] for row in rows.get("integrations.NotificationDestination", ())
    }
    for label in (
        "integrations.DestinationCategoryScope",
        "integrations.DestinationMachineScope",
        "integrations.DestinationMachineTypeScope",
    ):
        rows[label] = tuple(
            row
            for row in rows.get(label, ())
            if row["destination_id"] in kept_destinations
        )


def _referenced_user_ids(rows):
    result = set()
    for (fidelity, label, field_name), edge in USER_EDGES.items():
        if fidelity is not Fidelity.PORTABLE or not edge.included or label not in rows:
            continue
        model = apps.get_model(label)
        field = model._meta.get_field(field_name)
        key = field_name if edge.raw else field.attname
        result.update(row[key] for row in rows[label] if row.get(key) is not None)
    return result


def validate_machine_operator_closure(rows, makerspace_id):
    """Return the exact decision-22 tuple catalog or fail on any missing FK."""
    machine_rows = {row["id"]: row for row in rows.get("machines.Machine", ())}
    user_ids = {row["id"] for row in rows.get("accounts.User", ())}
    result = []
    for row in rows.get("machines.MachineOperator", ()):
        machine = machine_rows.get(row["machine_id"])
        if machine is None or machine["makerspace_id"] != makerspace_id:
            raise TenantDumpProjectionError(
                f"MachineOperator {row['id']} references a machine absent from the artifact"
            )
        if row["user_id"] not in user_ids:
            raise TenantDumpProjectionError(
                f"MachineOperator {row['id']} references a user absent from the artifact"
            )
        assigner = row["assigned_by_id"]
        if assigner is not None and assigner not in user_ids:
            raise TenantDumpProjectionError(
                f"MachineOperator {row['id']} references an assigner absent from the artifact"
            )
        result.append(
            {
                "source_machine_operator_id": row["id"],
                "source_makerspace_id": makerspace_id,
                "source_machine_id": row["machine_id"],
                "source_user_id": row["user_id"],
                "access_level": row["access_level"],
                "source_assigned_by_id": assigner,
                "assigned_at": _json_value(row["assigned_at"]),
                "machine_fingerprint": _machine_fingerprint(machine),
            }
        )
    return tuple(
        sorted(
            result,
            key=lambda item: (item["source_machine_id"], item["source_user_id"]),
        )
    )


def _machine_fingerprint(row):
    payload = {
        "created_at": _json_value(row["created_at"]),
        "location": row["location"],
        "machine_pk": row["id"],
        "machine_type_slug": row["_machine_type_slug"],
        "name": row["name"],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _LosslessJSONEncoder(DjangoJSONEncoder):
    """Keep full timestamp precision, unlike the base encoder.

    DjangoJSONEncoder truncates datetimes to milliseconds for ECMA-262
    compatibility. Lane D carries provenance -- `assigned_at` is evidence of who
    granted machine authority and when -- and PostgreSQL stores microseconds, so
    the value the target receives must be the value the source recorded, not a
    rounded one.
    """

    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def _json_value(value):
    return json.loads(json.dumps(value, cls=_LosslessJSONEncoder))
