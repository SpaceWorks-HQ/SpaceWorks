"""Lossless reconstruction of a verified readable main from unsealed slices."""

from dataclasses import dataclass
import hashlib
import json

from django.apps import apps
from django.db import connections, transaction

from apps.backup.main_projection_verification import verify_readable_main
from apps.backup.projection_databases import restore_dump, temporary_database
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.source_reservations import _evaluate_rule, _qualifying_count
from apps.data_export.datasets import DATASET_SPECS


@dataclass(frozen=True)
class ReconstructionPass:
    source_counts: dict[str, int]
    main_counts: dict[str, int]
    component_counts: dict[str, dict[str, int]]
    component_key_digests: dict[str, dict[str, str]]


def verify_reconstruction(
    main_dump, unsealed_slices, rules, expected_full_ledger, reservation_capture,
    *, postgres_major,
):
    """Exercise dependency and reversed arrival order against fresh main clones."""

    slices = tuple(unsealed_slices)
    verified = None
    for order in (slices, tuple(reversed(slices))):
        with temporary_database("reconstruction") as (using, database_name):
            restore_dump(main_dump, database_name)
            before = _reservation_measurements(
                using, (), reservation_capture, postgres_major
            )
            _load_slices(using, order)
            verify_readable_main(using, rules, (), expected_full_ledger)
            after = _reservation_measurements(
                using, order, reservation_capture, postgres_major
            )
            candidate = ReconstructionPass(
                source_counts=after["source_counts"],
                main_counts=before["source_counts"],
                component_counts=after["component_counts"],
                component_key_digests=after["component_key_digests"],
            )
            if verified is not None and candidate != verified:
                raise BackupBuildError(
                    "Reversed slice arrival changed reservation reconstruction facts."
                )
            verified = candidate
    return verified


def _load_slices(using, slices):
    fixtures = _fixture_records(_root(item) for item in slices)
    ordered_models = _dependency_order(fixtures)
    seen = set()
    with transaction.atomic(using=using):
        connection = connections[using]
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
            cursor.execute("SET LOCAL app.allow_immutable_insert = 'on'")
            for model in ordered_models:
                for item in fixtures[model]:
                    identity = (model._meta.label, str(item["pk"]))
                    if identity in seen:
                        continue
                    _insert_fixture(cursor, model, item)
                    seen.add(identity)
            for item in slices:
                root = _root(item)
                _apply_boundary_deltas(cursor, root)
                _apply_external_deltas(cursor, root)


def _reservation_measurements(using, slices, capture, postgres_major):
    rules = {item.identity: item for item in load_unique_rules(using)}
    models_by_table = {
        model._meta.db_table: model for model in apps.get_models()
        if model._meta.managed and not model._meta.proxy
    }
    source_counts = {}
    component_counts = {}
    component_key_digests = {}
    fixture_pks = {
        str(item.frozen.slice_id): {
            model: tuple(record["pk"] for record in records)
            for model, records in _fixture_records((_root(item),)).items()
        }
        for item in slices
    }
    for expected in capture.rule_proofs:
        identity = expected["constraint_identity"]
        rule = rules.get(identity)
        if rule is None:
            raise BackupBuildError("Reconstruction lost a reservation unique rule.")
        model = models_by_table[rule.table]
        all_rows = model._base_manager.using(using).all()
        source_counts[identity] = _qualifying_count(using, rule, all_rows)
        for component_id, by_model in fixture_pks.items():
            primary_keys = by_model.get(model, ())
            queryset = (
                all_rows.filter(pk__in=primary_keys)
                if primary_keys
                else all_rows.none()
            )
            count = _qualifying_count(using, rule, queryset)
            component_counts.setdefault(identity, {})[component_id] = count
            framed = _evaluate_rule(
                using, rule, queryset, postgres_major, canonicalize=(
                    expected["reservation_mode"] == "high_entropy_commitment"
                ),
            )
            raw = b"".join(
                len(value).to_bytes(8, "big") + value
                for value in sorted(item for item in framed if item is not None)
            )
            component_key_digests.setdefault(identity, {})[component_id] = (
                hashlib.sha256(raw).hexdigest()
            )
    return {
        "source_counts": source_counts,
        "component_counts": component_counts,
        "component_key_digests": component_key_digests,
    }


def _root(item):
    return item.plaintext if hasattr(item, "plaintext") else item


def _fixture_records(slices):
    result = {}
    for root in slices:
        rows_root = root / "rows"
        for label in sorted(DATASET_SPECS):
            model = apps.get_model(label)
            path = rows_root / f"{label.lower().replace('.', '_')}.json"
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BackupBuildError(
                    f"Reconstruction cannot read the {label} slice rows."
                ) from exc
            result.setdefault(model, []).extend(records)
        for path in (root / "inverse" / "boundary-deltas.json", rows_root / "external_references.json"):
            for item in _read_json(path):
                preimage = item.get("row_preimage")
                if preimage:
                    result.setdefault(apps.get_model(preimage["model"]), []).append(preimage)
    return result


def _dependency_order(fixtures):
    models = set(fixtures)
    dependencies = {
        model: {
            field.related_model
            for field in model._meta.concrete_fields
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
            # PostgreSQL will still accept a genuinely deferrable FK cycle.  A
            # non-deferrable cycle aborts the verifier rather than disabling it.
            ready = [min(dependencies, key=lambda model: model._meta.label_lower)]
        for model in ready:
            result.append(model)
            dependencies.pop(model)
        for required in dependencies.values():
            required.difference_update(ready)
    return result


def _insert_fixture(cursor, model, item):
    fields = {model._meta.pk.name: item["pk"], **item["fields"]}
    columns, values = [], []
    for name, raw in fields.items():
        field = model._meta.get_field(name)
        columns.append(cursor.db.ops.quote_name(field.column))
        value = field.to_python(raw)
        values.append(field.get_db_prep_save(value, connection=cursor.db))
    table = cursor.db.ops.quote_name(model._meta.db_table)
    placeholders = ", ".join(["%s"] * len(values))
    cursor.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )


def _apply_boundary_deltas(cursor, root):
    for item in _read_json(root / "inverse" / "boundary-deltas.json"):
        if "field_preimage" not in item:
            continue
        _update_field(
            cursor, apps.get_model(item["model"]), item["row_pk"],
            item["field"], item["field_preimage"],
        )


def _apply_external_deltas(cursor, root):
    for item in _read_json(root / "rows" / "external_references.json"):
        if "field_preimage" not in item or "row_pk" not in item:
            continue
        model_label, field_name = item["type"].rsplit(".", 1)
        _update_field(
            cursor, apps.get_model(model_label), item["row_pk"],
            field_name, item["field_preimage"],
        )


def _update_field(cursor, model, pk, field_name, raw):
    field = model._meta.get_field(field_name)
    value = field.get_db_prep_save(field.to_python(raw), connection=cursor.db)
    quote = cursor.db.ops.quote_name
    cursor.execute(
        f"UPDATE {quote(model._meta.db_table)} SET {quote(field.column)} = %s "
        f"WHERE {quote(model._meta.pk.column)} = %s",
        [value, model._meta.pk.get_db_prep_value(pk, cursor.db)],
    )


def _read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupBuildError(f"Reconstruction ledger is unreadable: {path.name}.") from exc
    if not isinstance(value, list):
        raise BackupBuildError(f"Reconstruction ledger is not a list: {path.name}.")
    return value
