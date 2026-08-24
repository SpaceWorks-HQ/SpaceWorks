"""Database-aware readiness checks bound to the immutable host marker."""

import hashlib

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from .host_marker import MarkerError, read_marker
from .process_roles import ProcessRole, admission_for


class HostReadinessError(RuntimeError):
    pass


def _identity(cursor):
    cursor.execute("SELECT current_database(), oid FROM pg_database WHERE datname = current_database()")
    return cursor.fetchone()


def _relation_facts(cursor, item):
    cursor.execute(
        "SELECT relation.oid FROM pg_class AS relation "
        "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
        "WHERE namespace.nspname = %s AND relation.relname = %s "
        "AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')",
        [item["schema"], item["table"]],
    )
    if cursor.fetchone()[0] is None:
        raise HostReadinessError("Declared readiness relation does not exist.")
    schema = connection.ops.quote_name(item["schema"])
    table = connection.ops.quote_name(item["table"])
    cursor.execute(
        f"SELECT COUNT(*), COALESCE("  # identifiers were validated by host_marker
        f"jsonb_agg(to_jsonb(snapshot) ORDER BY to_jsonb(snapshot)::text)::text, '[]') "
        f"FROM {schema}.{table} AS snapshot"
    )
    count, canonical_rows = cursor.fetchone()
    digest = hashlib.sha256(canonical_rows.encode("utf-8")).hexdigest()
    return count, digest


def _verify_relations(cursor, label, declarations):
    total = 0
    for item in declarations:
        try:
            actual, digest = _relation_facts(cursor, item)
        except Exception as exc:
            raise HostReadinessError(f"{label} relation is unavailable.") from exc
        if actual != item["expected_rows"] or digest != item["sha256"]:
            raise HostReadinessError(f"{label} rows or digest disagree with the host marker.")
        total += actual
    return total


def _verify_fences(cursor, declarations):
    for item in declarations:
        cursor.execute(
            "SELECT trigger.tgenabled, pg_get_triggerdef(trigger.oid, true) "
            "FROM pg_trigger AS trigger "
            "JOIN pg_class AS relation ON relation.oid = trigger.tgrelid "
            "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
            "WHERE namespace.nspname = %s AND relation.relname = %s "
            "AND trigger.tgname = %s AND NOT trigger.tgisinternal",
            [item["schema"], item["table"], item["trigger"]],
        )
        row = cursor.fetchone()
        if row is None or row[0] not in {"O", "A"}:
            raise HostReadinessError("A required database fence is missing or disabled.")
        digest = hashlib.sha256(row[1].encode("utf-8")).hexdigest()
        if digest != item["definition_sha256"]:
            raise HostReadinessError("A required database fence definition disagrees.")
    return len(declarations)


def assert_host_ready(marker_path):
    try:
        marker = read_marker(marker_path)
    except MarkerError as exc:
        raise HostReadinessError(str(exc)) from exc
    if not admission_for(marker.state, ProcessRole.BACKEND).admitted:
        raise HostReadinessError("Marker state does not admit a backend readiness process.")
    try:
        bound_database = marker.require_bound_database()
    except MarkerError as exc:
        raise HostReadinessError(str(exc)) from exc
    try:
        with connection.cursor() as cursor:
            database_name, database_oid = _identity(cursor)
            if (database_name, database_oid) != (
                bound_database.name,
                bound_database.oid,
            ):
                raise HostReadinessError("Live database identity disagrees with the host marker.")
            reservations = _verify_relations(cursor, "Reservation", marker.reservations)
            fences = _verify_fences(cursor, marker.fences)
            not_restored = _verify_relations(cursor, "Not-restored", marker.not_restored)
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise HostReadinessError("Database migrations are not at the application leaves.")
    except HostReadinessError:
        raise
    except Exception as exc:
        raise HostReadinessError("Host/database readiness facts could not be verified.") from exc
    return {
        "marker_state": marker.state.value,
        "database_routing": marker.database_routing,
        "database_oid": database_oid,
        "migrations": "applied",
        "reservations": reservations,
        "fences": fences,
        "not_restored": not_restored,
    }
