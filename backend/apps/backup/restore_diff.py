"""All-table restore comparison from one live REPEATABLE READ snapshot."""

import base64
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import json
import uuid

from django.db import connections, transaction


# Presentation hints only. Neither set removes a table from comparison.
AUTHORITY_MODELS = frozenset({
    "accounts_user", "accounts_socialidentity", "accounts_devicegrant",
    "accounts_platformloginmethods", "accounts_oidcprovider", "apiclients_apiclient",
    "makerspaces_makerspace", "makerspaces_makerspacemembership",
    "makerspaces_makerspacerole", "django_session", "token_blacklist_outstandingtoken",
    "token_blacklist_blacklistedtoken",
})
NOISY_TABLES = frozenset({
    "audit_auditlog", "integrations_emaillog", "operations_periodictaskrun",
    "axes_accessattempt", "axes_accesslog", "axes_accessfailurelog",
})


def compute_restore_diff(
    *, archive_using, live_using="default", sample_limit=100, within_snapshot=None
):
    """Compare every table, keeping every live read inside one read-only snapshot."""
    live = connections[live_using]
    archive = connections[archive_using]
    with transaction.atomic(using=live_using):
        with live.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT transaction_timestamp()")
            snapshot_at = cursor.fetchone()[0]
        live_tables = set(live.introspection.table_names())
        archive_tables = set(archive.introspection.table_names())
        results = []
        for table in sorted(live_tables | archive_tables):
            result = _compare_table(live, archive, table, live_tables, archive_tables, sample_limit)
            result["security_relevant"] = table in AUTHORITY_MODELS
            result["noisy"] = table in NOISY_TABLES
            results.append(result)
        changed = [row for row in results if row["changed"]]
        changed.sort(key=lambda row: (not row["security_relevant"], row["noisy"], row["table"]))
        report = {
            "snapshot_at": snapshot_at.isoformat(),
            "isolation": "repeatable read, read only",
            "tables_compared": len(results),
            "tables_changed": len(changed),
            "tables": changed,
        }
        if within_snapshot is not None:
            within_snapshot(report)
        return report


def _compare_table(live, archive, table, live_tables, archive_tables, sample_limit):
    live_exists, archive_exists = table in live_tables, table in archive_tables
    live_summary = _table_summary(live, table) if live_exists else {"row_count": 0, "content_hash": None}
    archive_summary = _table_summary(archive, table) if archive_exists else {"row_count": 0, "content_hash": None}
    changed = live_summary != archive_summary or live_exists != archive_exists
    result = {
        "table": table,
        "changed": changed,
        "live": {"exists": live_exists, **live_summary},
        "archive": {"exists": archive_exists, **archive_summary},
    }
    if changed:
        result["row_diff"] = _row_descent(
            live, archive, table, live_exists, archive_exists, sample_limit
        )
    return result


def _table_summary(connection, table):
    quoted = connection.ops.quote_name(table)
    sql = (
        "SELECT COUNT(*), md5(COALESCE(string_agg(row_hash, '' ORDER BY row_hash), '')) "
        f"FROM (SELECT md5(row_to_json(t)::text) AS row_hash FROM {quoted} t) rows"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql)
        count, digest = cursor.fetchone()
    return {"row_count": count, "content_hash": digest}


def _row_descent(live, archive, table, live_exists, archive_exists, sample_limit):
    live_rows, live_pk = _rows(live, table) if live_exists else ([], ())
    archive_rows, archive_pk = _rows(archive, table) if archive_exists else ([], ())
    pk_columns = live_pk or archive_pk
    if pk_columns and live_pk == archive_pk:
        return _keyed_descent(live_rows, archive_rows, pk_columns, sample_limit)
    live_counts = Counter(_canonical_hash(row) for row in live_rows)
    archive_counts = Counter(_canonical_hash(row) for row in archive_rows)
    removed = list((live_counts - archive_counts).elements())
    added = list((archive_counts - live_counts).elements())
    return {
        "identity": "row_content_hash",
        "removed_count": len(removed),
        "added_count": len(added),
        "removed": removed[:sample_limit],
        "added": added[:sample_limit],
        "truncated": len(removed) > sample_limit or len(added) > sample_limit,
    }


def _rows(connection, table):
    quoted = connection.ops.quote_name(table)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {quoted}")
        columns = [item.name for item in cursor.description]
        rows = [dict(zip(columns, (_json_value(value) for value in values))) for values in cursor.fetchall()]
        constraints = connection.introspection.get_constraints(cursor, table)
    pk = next((tuple(value["columns"]) for value in constraints.values() if value.get("primary_key")), ())
    return rows, pk


def _keyed_descent(live_rows, archive_rows, pk_columns, sample_limit):
    key = lambda row: tuple(row[column] for column in pk_columns)
    live_by_key = {key(row): row for row in live_rows}
    archive_by_key = {key(row): row for row in archive_rows}
    removed_keys = sorted(set(live_by_key) - set(archive_by_key), key=str)
    added_keys = sorted(set(archive_by_key) - set(live_by_key), key=str)
    changed_keys = sorted(
        (item for item in set(live_by_key) & set(archive_by_key) if live_by_key[item] != archive_by_key[item]),
        key=str,
    )
    samples = []
    for item in changed_keys[:sample_limit]:
        live_row, archive_row = live_by_key[item], archive_by_key[item]
        fields = sorted(name for name in set(live_row) | set(archive_row) if live_row.get(name) != archive_row.get(name))
        samples.append({
            "key": item,
            "changed_fields": fields,
            "live_hash": _canonical_hash(live_row),
            "archive_hash": _canonical_hash(archive_row),
        })
    return {
        "identity": list(pk_columns),
        "removed_count": len(removed_keys),
        "added_count": len(added_keys),
        "changed_count": len(changed_keys),
        "removed_keys": removed_keys[:sample_limit],
        "added_keys": added_keys[:sample_limit],
        "changed_rows": samples,
        "truncated": any(len(items) > sample_limit for items in (removed_keys, added_keys, changed_keys)),
    }


def _json_value(value):
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime, date, Decimal, uuid.UUID)):
        return str(value)
    return value


def _canonical(row):
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_hash(row):
    import hashlib

    return hashlib.sha256(_canonical(row).encode()).hexdigest()
