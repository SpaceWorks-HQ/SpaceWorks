"""Raw fixture staging and registered fill-only handlers for E8."""

from dataclasses import dataclass
import json

from django.apps import apps
from django.db import connections, transaction

from apps.backup.slice_merge_database import merge_role, protect_target_tables
from apps.backup.slice_merge_cleanup import drop_staging_schema
from apps.backup.slice_merge_raw import (
    dek_fixture as _dek_fixture,
    dependency_order as _dependency_order,
    prepared_record as _prepared_record,
    row_exists as _row_exists,
    slice_deltas as _slice_deltas,
    slice_fixtures as _slice_fixtures,
)
from apps.backup.slice_merge_types import SliceMergeError


RAW_HANDLER_VERSION = "spaceworks-b1-raw-fixture-v1"


@dataclass(frozen=True)
class StagedGroup:
    schema: str
    component_ids: tuple[object, ...]
    fixtures: tuple[tuple[object, dict, object], ...]
    deltas: tuple[tuple[object, dict, object], ...]
    tables: frozenset[str]


def stage_group(schema, slices, *, using="default"):
    """Load raw serialized values without constructing mapped model instances."""
    fixtures = []
    deltas = []
    seen = {}
    for item in slices:
        component_id = item.component.component_id
        for model, record in _slice_fixtures(item.root):
            identity = (model._meta.label_lower, json.dumps(record["pk"], sort_keys=True, default=str))
            if identity in seen:
                if seen[identity][1] != record:
                    raise SliceMergeError("Cross-linked slices disagree on a shared raw row.")
                continue
            seen[identity] = (component_id, record)
            fixtures.append((model, record, component_id))
        deltas.extend(
            (model, delta, component_id) for model, delta in _slice_deltas(item.root)
        )
    tables = frozenset(
        [model._meta.db_table for model, _record, _component in fixtures]
        + [model._meta.db_table for model, _delta, _component in deltas]
    )
    _create_schema(schema, slices, tables, using=using)
    try:
        for model, record, component_id in fixtures:
            _insert_staged(schema, model, record, component_id, using=using)
        for model, delta, component_id in deltas:
            _insert_delta(schema, model, delta, component_id, using=using)
        protect_target_tables(schema, tables, using=using)
    except Exception:
        drop_staging_schema(schema, using=using)
        raise
    return StagedGroup(
        schema,
        tuple(item.component.component_id for item in slices),
        tuple(fixtures), tuple(deltas), tables,
    )


def add_target_deks(group, target_deks, *, using="default"):
    model = apps.get_model("encryption.MakerspaceEncryptionKey")
    additions = [
        (model, _dek_fixture(row), component_id)
        for component_id, rows in target_deks.items() for row in rows
    ]
    if not additions:
        return group
    table = model._meta.db_table
    connection = connections[using]
    quote = connection.ops.quote_name
    if table not in group.tables:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TABLE {quote(group.schema)}.{quote(table)} "
                f"(LIKE public.{quote(table)} INCLUDING GENERATED)"
            )
            cursor.execute(
                f"ALTER TABLE {quote(group.schema)}.{quote(table)} "
                "ADD COLUMN __b1_component_id uuid NOT NULL"
            )
    for _model, record, component_id in additions:
        _insert_staged(group.schema, model, record, component_id, using=using)
    tables = frozenset({*group.tables, table})
    protect_target_tables(group.schema, tables, using=using)
    return StagedGroup(
        group.schema, group.component_ids,
        (*group.fixtures, *additions), group.deltas, tables,
    )


def apply_staged(group, operation_id, *, using="default"):
    """Run only the registered raw INSERT and exact inverse-delta handlers."""
    connection = connections[using]
    order = _dependency_order({model for model, _record, _component in group.fixtures})
    by_model = {model: [] for model in order}
    for model, record, component_id in group.fixtures:
        by_model[model].append((record, component_id))
    with transaction.atomic(using=using):
        from apps.backup.models import B1ReservationEntry, B1RestoreComponentState

        component_ids = group.component_ids
        list(B1RestoreComponentState.objects.using(using).select_for_update().filter(
            operation_id=operation_id, component_id__in=component_ids
        ).order_by("component_id"))
        list(B1ReservationEntry.objects.using(using).select_for_update().filter(
            operation_id=operation_id, component_id__in=component_ids
        ).order_by("component_id", "pk"))
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
            for model in order:
                for record, component_id in by_model[model]:
                    if _row_exists(cursor, model, record["pk"]):
                        raise SliceMergeError("A staged row would overwrite an occupied target identity.")
                    with merge_role(cursor, operation_id, component_id, group.schema):
                        _insert_public(cursor, model, record)
            for model, delta, component_id in group.deltas:
                with merge_role(cursor, operation_id, component_id, group.schema):
                    _apply_delta(cursor, model, delta)
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def verify_staged_rows(group, *, using="default"):
    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for model, record, _component_id in group.fixtures:
            table = quote(model._meta.db_table)
            pk = model._meta.pk
            cursor.execute(
                f"SELECT to_jsonb(target) FROM {table} target WHERE {quote(pk.column)} = %s",
                [pk.get_db_prep_value(record["pk"], connection)],
            )
            actual = cursor.fetchone()
            cursor.execute(
                f"SELECT to_jsonb(staged) - '__b1_component_id' FROM "
                f"{quote(group.schema)}.{table} staged WHERE {quote(pk.column)} = %s",
                [pk.get_db_prep_value(record["pk"], connection)],
            )
            expected = cursor.fetchone()
            if actual is None or expected is None or actual[0] != expected[0]:
                raise SliceMergeError("A merged row does not match its raw staged value.")
        for model, delta, _component_id in group.deltas:
            field = model._meta.get_field(delta["field"])
            pk = model._meta.pk
            cursor.execute(
                f"SELECT {quote(field.column)} FROM {quote(model._meta.db_table)} "
                f"WHERE {quote(pk.column)} = %s",
                [pk.get_db_prep_value(delta["row_pk"], connection)],
            )
            row = cursor.fetchone()
            expected = field.get_db_prep_save(field.to_python(delta["new_value"]), connection)
            if row is None or row[0] != expected:
                raise SliceMergeError("A declared inverse delta was not applied exactly.")


def _create_schema(schema, slices, tables, *, using):
    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA {quote(schema)}")
        cursor.execute(
            f"CREATE TABLE {quote(schema)}.backup_b1_context "
            "(operation_id uuid NOT NULL, component_id uuid PRIMARY KEY)"
        )
        cursor.executemany(
            f"INSERT INTO {quote(schema)}.backup_b1_context VALUES (%s, %s)",
            [(item.component.operation_id, item.component.component_id) for item in slices],
        )
        cursor.execute(
            f"CREATE TABLE {quote(schema)}.backup_b1_deltas ("
            "component_id uuid NOT NULL, table_name text NOT NULL, row_pk jsonb NOT NULL, "
            "column_name text NOT NULL, old_value jsonb NOT NULL, new_value jsonb NOT NULL)"
        )
        for table in sorted(tables):
            cursor.execute(
                f"CREATE TABLE {quote(schema)}.{quote(table)} "
                f"(LIKE public.{quote(table)} INCLUDING GENERATED)"
            )
            cursor.execute(
                f"ALTER TABLE {quote(schema)}.{quote(table)} "
                "ADD COLUMN __b1_component_id uuid NOT NULL"
            )


def _insert_staged(schema, model, record, component_id, *, using):
    connection = connections[using]
    with connection.cursor() as cursor:
        columns, values = _prepared_record(model, record, connection)
        quote = connection.ops.quote_name
        names = [quote(value) for value in columns] + ["__b1_component_id"]
        cursor.execute(
            f"INSERT INTO {quote(schema)}.{quote(model._meta.db_table)} "
            f"({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})",
            [*values, component_id],
        )


def _insert_delta(schema, model, delta, component_id, *, using):
    connection = connections[using]
    field = model._meta.get_field(delta["field"])
    pk = model._meta.pk.get_db_prep_value(delta["row_pk"], connection)
    old_value = field.get_db_prep_save(field.to_python(delta["old_value"]), connection)
    new_value = field.get_db_prep_save(field.to_python(delta["new_value"]), connection)
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {quote(schema)}.backup_b1_deltas VALUES "
            "(%s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb)",
            [component_id, model._meta.db_table, json.dumps(pk, default=str), field.column,
             json.dumps(old_value, default=str), json.dumps(new_value, default=str)],
        )


def _insert_public(cursor, model, record):
    columns, values = _prepared_record(model, record, cursor.db)
    quote = cursor.db.ops.quote_name
    cursor.execute(
        f"INSERT INTO {quote(model._meta.db_table)} "
        f"({', '.join(quote(value) for value in columns)}) "
        f"VALUES ({', '.join(['%s'] * len(values))})",
        values,
    )


def _apply_delta(cursor, model, delta):
    field = model._meta.get_field(delta["field"])
    pk = model._meta.pk
    value = field.get_db_prep_save(field.to_python(delta["new_value"]), cursor.db)
    cursor.execute(
        f"UPDATE {cursor.db.ops.quote_name(model._meta.db_table)} SET "
        f"{cursor.db.ops.quote_name(field.column)} = %s WHERE "
        f"{cursor.db.ops.quote_name(pk.column)} = %s",
        [value, pk.get_db_prep_value(delta["row_pk"], cursor.db)],
    )
    if cursor.rowcount != 1:
        raise SliceMergeError("A declared inverse delta does not name one main-owned row.")
