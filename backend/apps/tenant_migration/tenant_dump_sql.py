"""Raw SQL operations and postconditions for a Lane D scratch database."""

from uuid import UUID

from django.apps import apps
from django.db import connections

from apps.data_export.datasets import DATASET_SPECS

from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_graph import model_dependency_order
from .tenant_dump_model_catalog import (
    AUTO_CREATED_TABLE_RULES,
    FIRST_PARTY_MODEL_RULES,
    THIRD_PARTY_MODEL_RULES,
)
from .tenant_dump_types import ModelDisposition

_FIXED_BOOTSTRAP_LABELS = frozenset({"encryption.PiiGlobalWriteFence"})
_TARGET_DERIVED_LABELS = frozenset(
    {
        "encryption.PiiMakerspaceWriteFence",
        "makerspaces.MakerspaceRole",
        "machines.RoleMachineTypeScope",
    }
)


def empty_source_disposition_tables(using):
    """Remove migration-seeded operational rows that D1 marks DROP/EMPTY."""
    rules = {
        **FIRST_PARTY_MODEL_RULES,
        **AUTO_CREATED_TABLE_RULES,
        **THIRD_PARTY_MODEL_RULES,
    }
    labels = {
        label
        for label, rule in rules.items()
        if rule.disposition in {ModelDisposition.DROP, ModelDisposition.EMPTY}
        and label not in _FIXED_BOOTSTRAP_LABELS | _TARGET_DERIVED_LABELS
    }
    models = tuple(apps.get_model(label) for label in labels)
    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for model in reversed(model_dependency_order(models)):
            cursor.execute(f"DELETE FROM {quote(model._meta.db_table)}")


def verify_source_disposition_tables_empty(using):
    rules = {
        **FIRST_PARTY_MODEL_RULES,
        **AUTO_CREATED_TABLE_RULES,
        **THIRD_PARTY_MODEL_RULES,
    }
    tables = {
        apps.get_model(label)._meta.db_table
        for label, rule in rules.items()
        if rule.disposition in {ModelDisposition.DROP, ModelDisposition.EMPTY}
        and label not in _FIXED_BOOTSTRAP_LABELS
        # Target-owned defaults are inserted after source rows have been discarded.
        and label not in _TARGET_DERIVED_LABELS
    }
    verify_tables_empty(using, tables)


def delete_portable_rows(using, makerspace_id, models):
    """Delete only each declared portable predicate, children before parents."""
    connection = connections[using]
    for model in reversed(model_dependency_order(models)):
        rule = FIRST_PARTY_MODEL_RULES[model._meta.label]
        if rule.disposition not in {
            ModelDisposition.PROJECT,
            ModelDisposition.PRESERVE_LIVE,
        }:
            continue
        _path, predicate = DATASET_SPECS[model._meta.label]
        if model._meta.label == "machines.MachineType":
            queryset = model._base_manager.using(using).filter(
                makerspace_id=makerspace_id
            )
        else:
            queryset = model._base_manager.using(using).filter(
                predicate.as_q(makerspace_id)
            )
        query = queryset.order_by().values("pk").query
        sql, params = query.get_compiler(using=using).as_sql()
        quote = connection.ops.quote_name
        table = quote(model._meta.db_table)
        pk = quote(model._meta.pk.column)
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {table} AS target USING ({sql}) AS portable "
                f"WHERE target.{pk} = portable.{quote('pk')}",
                params,
            )


def insert_rows(using, rows, *, batch_size=500):
    connection = connections[using]
    inserted = 0
    grouped = []
    for row in rows:
        if not grouped or grouped[-1][0] is not row.model:
            grouped.append((row.model, []))
        grouped[-1][1].append(row)
    with connection.cursor() as cursor:
        for model, model_rows in grouped:
            columns = tuple(field.column for field in model._meta.concrete_fields)
            quote = connection.ops.quote_name
            table = quote(model._meta.db_table)
            column_sql = ", ".join(quote(column) for column in columns)
            placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
            fields = {field.column: field for field in model._meta.concrete_fields}
            for offset in range(0, len(model_rows), batch_size):
                batch = model_rows[offset : offset + batch_size]
                parameters = [
                    fields[column].get_db_prep_save(row.values[column], connection)
                    for row in batch
                    for column in columns
                ]
                cursor.execute(
                    f"INSERT INTO {table} ({column_sql}) VALUES "
                    + ", ".join([placeholders] * len(batch)),
                    parameters,
                )
                inserted += len(batch)
    return inserted


def apply_deferred_foreign_keys(using, deferred, rows_by_identity):
    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for update in deferred:
            row = rows_by_identity[update.identity]
            cursor.execute(
                f"UPDATE {quote(row.model._meta.db_table)} "
                f"SET {quote(update.column)} = %s WHERE "
                f"{quote(row.model._meta.pk.column)} = %s",
                [update.value, row.values[row.model._meta.pk.column]],
            )
            if cursor.rowcount != 1:
                raise TenantDumpVerificationError(
                    f"Nullable-cycle update missed {update.identity}."
                )


def insert_closed_tenant_fence(using, makerspace_id, operation_id):
    operation_id = UUID(str(operation_id))
    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO encryption_piimakerspacewritefence "
            "(makerspace_id, state, operation_id, operation_kind, actor_id, "
            "closed_at, opened_at) VALUES (%s, 'closed', %s, 'tenant_import', "
            "NULL, CURRENT_TIMESTAMP, NULL)",
            [makerspace_id, operation_id],
        )
        cursor.execute("SET LOCAL app.pii_fence_operation = %s", [str(operation_id)])


def serialize_open_tenant_fence(using, makerspace_id, operation_id):
    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE encryption_piimakerspacewritefence SET state = 'open', "
            "operation_id = NULL, operation_kind = NULL, actor_id = NULL, "
            "closed_at = NULL, opened_at = CURRENT_TIMESTAMP "
            "WHERE makerspace_id = %s AND state = 'closed' "
            "AND operation_id = %s AND operation_kind = 'tenant_import'",
            [makerspace_id, UUID(str(operation_id))],
        )
        if cursor.rowcount != 1:
            raise TenantDumpVerificationError("The Lane D PII fence could not be reopened.")


def verify_open_tenant_fence(using, makerspace_id):
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT state, operation_id, operation_kind FROM "
            "encryption_piiglobalwritefence WHERE id = 1"
        )
        global_row = cursor.fetchone()
        cursor.execute(
            "SELECT state, operation_id, operation_kind FROM "
            "encryption_piimakerspacewritefence WHERE makerspace_id = %s",
            [makerspace_id],
        )
        row = cursor.fetchone()
    if global_row != ("open", None, None) or row != ("open", None, None):
        raise TenantDumpVerificationError("The dumped PII fence state is not open.")


def verify_foreign_key_closure(using):
    """Walk every public FK and reject a dangling stored reference."""
    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT child.relname, parent.relname,
                   array_agg(child_att.attname ORDER BY keys.ordinality),
                   array_agg(parent_att.attname ORDER BY keys.ordinality)
              FROM pg_constraint constraint_row
              JOIN pg_class child ON child.oid = constraint_row.conrelid
              JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
              JOIN pg_class parent ON parent.oid = constraint_row.confrelid
              JOIN unnest(constraint_row.conkey, constraint_row.confkey)
                   WITH ORDINALITY AS keys(child_num, parent_num, ordinality) ON TRUE
              JOIN pg_attribute child_att
                ON child_att.attrelid = child.oid AND child_att.attnum = keys.child_num
              JOIN pg_attribute parent_att
                ON parent_att.attrelid = parent.oid AND parent_att.attnum = keys.parent_num
             WHERE constraint_row.contype = 'f'
               AND child_ns.nspname = 'public'
             GROUP BY constraint_row.oid, child.relname, parent.relname
             ORDER BY child.relname, parent.relname, constraint_row.oid
            """
        )
        constraints = cursor.fetchall()
        quote = connection.ops.quote_name
        for child, parent, child_columns, parent_columns in constraints:
            present = " AND ".join(
                f"child.{quote(column)} IS NOT NULL" for column in child_columns
            )
            equal = " AND ".join(
                f"parent.{quote(target)} = child.{quote(source)}"
                for source, target in zip(child_columns, parent_columns, strict=True)
            )
            cursor.execute(
                f"SELECT EXISTS (SELECT 1 FROM {quote(child)} AS child "
                f"WHERE {present} AND NOT EXISTS (SELECT 1 FROM {quote(parent)} "
                f"AS parent WHERE {equal}))"
            )
            if cursor.fetchone()[0]:
                raise TenantDumpVerificationError(
                    f"Dangling FK closure in {child} -> {parent}."
                )


def verify_tables_empty(using, table_names):
    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for table in sorted(table_names):
            cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {quote(table)} LIMIT 1)")
            if cursor.fetchone()[0]:
                raise TenantDumpVerificationError(
                    f"Lane D requires {table} to be empty."
                )
