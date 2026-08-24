"""Parsing primitives for E8's registered raw fixture handler."""

import json
from pathlib import Path

from django.apps import apps
from django.utils import timezone

from apps.backup.main_projection_registry import boundary_rules, table_rules
from apps.backup.slice_merge_types import SliceMergeError
from apps.data_export.datasets import DATASET_SPECS


def slice_fixtures(root):
    result = []
    rows = Path(root) / "rows"
    for label in sorted(DATASET_SPECS):
        model = apps.get_model(label)
        for record in _read_list(rows / f"{label.lower().replace('.', '_')}.json"):
            result.append((model, record))
    for path in (Path(root) / "inverse" / "boundary-deltas.json", rows / "external_references.json"):
        for item in _read_list(path):
            preimage = item.get("row_preimage")
            if preimage:
                result.append((apps.get_model(preimage["model"]), preimage))
    return result


def slice_deltas(root):
    result = []
    declared = {
        (rule.source_model._meta.label, rule.field.name, str(rule.disposition))
        for rule in boundary_rules(table_rules())
    }
    for item in _read_list(Path(root) / "inverse" / "boundary-deltas.json"):
        try:
            identity = (item["model"], item["field"], item["disposition"])
            if identity not in declared:
                raise ValueError
            if "field_preimage" in item:
                result.append((apps.get_model(item["model"]), {
                    "row_pk": item["row_pk"], "field": item["field"],
                    "old_value": None, "new_value": item["field_preimage"],
                }))
            elif "row_preimage" not in item:
                raise ValueError
        except (KeyError, LookupError, ValueError):
            raise SliceMergeError("A boundary inverse delta is not registry-declared.") from None
    for item in _read_list(Path(root) / "rows" / "external_references.json"):
        if "field_preimage" not in item or "row_pk" not in item:
            continue
        try:
            model_label, field_name = item["type"].rsplit(".", 1)
            if model_label == "operations.StockTransfer" and field_name in {"source", "destination"}:
                field_name = f"{field_name}_makerspace"
            model = apps.get_model(model_label)
            field = model._meta.get_field(field_name)
            if not field.is_relation or field.related_model._meta.label != "makerspaces.Makerspace":
                raise ValueError
            result.append((model, {
                "row_pk": item["row_pk"], "field": field_name,
                "old_value": None, "new_value": item["field_preimage"],
            }))
        except (KeyError, LookupError, ValueError):
            raise SliceMergeError("An external inverse delta is not registry-declared.") from None
    return result


def dek_fixture(row):
    now = timezone.now()
    return {
        "model": "encryption.makerspaceencryptionkey",
        "pk": row.row_identity,
        "fields": {
            "makerspace": row.makerspace_id,
            "version": row.version,
            "wrapped_dek": row.wrapped_dek,
            "broker_backend": row.broker_backend,
            "broker_key_id": row.broker_key_id,
            "status": row.status,
            "created_at": now,
            "rotated_at": now if row.status == "rotated" else None,
            "disabled_at": now if row.status == "disabled" else None,
        },
    }


def prepared_record(model, record, connection):
    raw_fields = {model._meta.pk.name: record["pk"], **record["fields"]}
    columns = []
    values = []
    try:
        for name, raw in raw_fields.items():
            field = model._meta.get_field(name)
            columns.append(field.column)
            values.append(field.get_db_prep_save(field.to_python(raw), connection))
    except Exception:
        raise SliceMergeError("A raw staged row cannot be represented by the target catalog.") from None
    if len(columns) != len(set(columns)):
        raise SliceMergeError("A raw staged row repeats a physical target column.")
    return columns, values


def row_exists(cursor, model, value):
    quote = cursor.db.ops.quote_name
    pk = model._meta.pk
    cursor.execute(
        f"SELECT 1 FROM {quote(model._meta.db_table)} WHERE {quote(pk.column)} = %s",
        [pk.get_db_prep_value(value, cursor.db)],
    )
    return cursor.fetchone() is not None


def dependency_order(models):
    dependencies = {
        model: {
            field.related_model for field in model._meta.concrete_fields
            if field.is_relation and field.related_model in models and field.related_model is not model
        }
        for model in models
    }
    result = []
    while dependencies:
        ready = sorted(
            (model for model, required in dependencies.items() if not required),
            key=lambda model: model._meta.label_lower,
        )
        if not ready:
            ready = [min(dependencies, key=lambda model: model._meta.label_lower)]
        for model in ready:
            result.append(model)
            dependencies.pop(model)
        for required in dependencies.values():
            required.difference_update(ready)
    return result


def _read_list(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SliceMergeError(f"A raw merge ledger is unreadable: {path.name}.") from None
    if not isinstance(value, list):
        raise SliceMergeError(f"A raw merge ledger is not a list: {path.name}.")
    return value
