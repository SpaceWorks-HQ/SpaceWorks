"""Derive a verified, sovereign-row-free readable main from the frozen dump."""

from pathlib import Path

from django.db import connections, transaction

from apps.backup.main_projection_registry import (
    BoundaryDisposition,
    EMPTIED_NON_MODEL_TABLES,
    RowDisposition,
    assert_catalog_matches,
    boundary_queryset,
    boundary_rules,
    sovereign_q,
    table_rules,
)
from apps.backup.main_projection_verification import verify_readable_main
from apps.backup.projection_databases import (
    dump_database,
    restore_dump,
    temporary_database,
)
from apps.backup.recipient_selection import BackupBuildError


def project_readable_main_dump(
    source_dump, destination, makerspace_ids, expected_ledger, *, sequence_facts=()
):
    """Project, dump, independently restore, and verify the readable main."""
    rules = table_rules()
    with temporary_database("projection") as (using, database_name):
        restore_dump(source_dump, database_name)
        assert_catalog_matches(using, rules)
        _apply_projection(using, rules, makerspace_ids)
        _install_sequence_high_water(using, sequence_facts)
        dump_database(database_name, destination)
    with temporary_database("verification") as (using, database_name):
        restore_dump(destination, database_name)
        verify_readable_main(
            using, rules, makerspace_ids, expected_ledger
        )
        _verify_sequence_high_water(using, sequence_facts)
    if not Path(destination).is_file() or Path(destination).stat().st_size <= 0:
        raise BackupBuildError("The verified readable-main dump is empty.")


def _apply_projection(using, rules, makerspace_ids):
    boundaries = boundary_rules(rules)
    with transaction.atomic(using=using):
        connection = connections[using]
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
            cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
            boundary_markers = []
            for index, rule in enumerate(boundaries):
                affected = boundary_queryset(rule, using, makerspace_ids)
                marker = _mark_queryset(cursor, using, affected, f"boundary_{index}")
                boundary_markers.append((rule, marker))
            table_markers = []
            for index, rule in enumerate(rules):
                if rule.disposition != RowDisposition.COPY_TO_SLICE:
                    continue
                affected = rule.model._base_manager.using(using).filter(
                    sovereign_q(rule.predicate, makerspace_ids)
                )
                marker = _mark_queryset(cursor, using, affected, f"table_{index}")
                table_markers.append((rule, marker))
            for rule, marker in boundary_markers:
                _apply_marker(cursor, rule.source_model, marker, field=(
                    rule.field
                    if rule.disposition == BoundaryDisposition.PROJECT_NULL_TO_SLICE
                    else None
                ))
            for rule, marker in reversed(table_markers):
                _apply_marker(cursor, rule.model, marker)
            for rule in rules:
                if rule.disposition == RowDisposition.OMIT_OPERATIONAL:
                    table = cursor.db.ops.quote_name(rule.model._meta.db_table)
                    cursor.execute(f"DELETE FROM {table}")
            for table in sorted(EMPTIED_NON_MODEL_TABLES):
                cursor.execute(f"DELETE FROM {cursor.db.ops.quote_name(table)}")


def _install_sequence_high_water(using, facts):
    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for fact in facts:
            qualified = f"{quote(fact['schema'])}.{quote(fact['sequence'])}"
            cursor.execute(
                "SELECT pg_catalog.setval(%s::regclass, %s, %s)",
                [
                    qualified,
                    fact["installed_last_value"],
                    fact["installed_is_called"],
                ],
            )


def _verify_sequence_high_water(using, facts):
    connection = connections[using]
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for fact in facts:
            cursor.execute(
                f"SELECT last_value, is_called FROM "
                f"{quote(fact['schema'])}.{quote(fact['sequence'])}"
            )
            if tuple(cursor.fetchone()) != (
                fact["installed_last_value"],
                fact["installed_is_called"],
            ):
                raise BackupBuildError(
                    f"Readable-main sequence {fact['sequence']} lost its high-water."
                )


def _mark_queryset(cursor, using, queryset, name):
    """Freeze the affected primary keys into a temp table with one `pk` column.

    `.values("pk")` aliases the selected column to "pk" regardless of what the
    model calls its primary key, so `_apply_marker` joins on that name rather
    than on the model's own column.
    """
    query = queryset.order_by().values("pk").query
    sql, params = query.get_compiler(using=using).as_sql()
    marker = f"lane_e_{name}"
    cursor.execute(f'CREATE TEMP TABLE "{marker}" ON COMMIT DROP AS {sql}', params)
    return marker


def _apply_marker(cursor, model, marker, field=None):
    quote = cursor.db.ops.quote_name
    table = quote(model._meta.db_table)
    pk = quote(model._meta.pk.column)
    marker_pk = quote("pk")
    marker_table = quote(marker)
    if field is None:
        cursor.execute(
            f"DELETE FROM {table} AS target USING {marker_table} AS ids "
            f"WHERE target.{pk} = ids.{marker_pk}"
        )
    else:
        column = quote(field.column)
        cursor.execute(
            f"UPDATE {table} AS target SET {column} = NULL "
            f"FROM {marker_table} AS ids WHERE target.{pk} = ids.{marker_pk}"
        )
