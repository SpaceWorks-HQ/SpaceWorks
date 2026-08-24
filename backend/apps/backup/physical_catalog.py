"""Canonical PostgreSQL catalog facts captured outside E7 candidate databases."""

import hashlib
import json

from django.db import connections

from apps.backup.reservation_canonicalizers import canonicalize_catalog_definition


_DEFINITION_COLUMNS = {"constraints": 7, "indexes": 7}


def physical_catalog_ledger(using="default"):
    connection = connections[using]
    result = {}
    with connection.cursor() as cursor:
        for name, sql in _QUERIES.items():
            cursor.execute(sql)
            result[name] = [list(row) for row in cursor.fetchall()]
    return result


def catalog_digest(ledger):
    return hashlib.sha256(json.dumps(
        _canonical_ledger(ledger),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")).hexdigest()


def catalog_difference(expected, actual):
    """Describe exact catalog-definition drift without exposing database rows."""

    differences = []
    for section in sorted(set(expected) | set(actual)):
        expected_rows = {
            _canonical_row(section, row): row for row in expected.get(section, ())
        }
        actual_rows = {
            _canonical_row(section, row): row for row in actual.get(section, ())
        }
        missing = [expected_rows[key] for key in sorted(expected_rows.keys() - actual_rows)]
        unexpected = [actual_rows[key] for key in sorted(actual_rows.keys() - expected_rows)]
        if missing or unexpected:
            differences.append({
                "section": section,
                "missing": missing,
                "unexpected": unexpected,
            })
    return differences


def _canonical_ledger(ledger):
    return {
        section: [_canonicalized_row(section, row) for row in rows]
        for section, rows in ledger.items()
    }


def _canonicalized_row(section, row):
    result = list(row)
    definition_column = _DEFINITION_COLUMNS.get(section)
    if definition_column is not None:
        result[definition_column] = canonicalize_catalog_definition(
            result[definition_column]
        )
    return result


def _canonical_row(section, row):
    return json.dumps(
        _canonicalized_row(section, row), separators=(",", ":"), default=str
    )


_QUERIES = {
    "extensions": """
        SELECT extname, extversion
          FROM pg_catalog.pg_extension
         ORDER BY extname
    """,
    "tables": """
        SELECT n.nspname, c.relname, c.relpersistence, c.relkind,
               c.relrowsecurity, c.relforcerowsecurity
          FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
         ORDER BY n.nspname, c.relname
    """,
    "constraints": """
        SELECT n.nspname, c.relname, con.conname, con.contype,
               con.condeferrable, con.condeferred, con.convalidated,
               pg_catalog.pg_get_constraintdef(con.oid, true)
          FROM pg_catalog.pg_constraint con
          JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
         ORDER BY n.nspname, c.relname, con.conname
    """,
    "indexes": """
        SELECT n.nspname, t.relname, i.relname,
               x.indisunique, x.indisprimary, x.indisvalid,
               COALESCE((to_jsonb(x)->>'indnullsnotdistinct')::boolean, false),
               pg_catalog.pg_get_indexdef(i.oid)
          FROM pg_catalog.pg_index x
          JOIN pg_catalog.pg_class i ON i.oid = x.indexrelid
          JOIN pg_catalog.pg_class t ON t.oid = x.indrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public'
         ORDER BY n.nspname, t.relname, i.relname
    """,
    "triggers": """
        SELECT n.nspname, c.relname, t.tgname, t.tgenabled,
               pg_catalog.pg_get_triggerdef(t.oid, true)
          FROM pg_catalog.pg_trigger t
          JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND NOT t.tgisinternal
         ORDER BY n.nspname, c.relname, t.tgname
    """,
}
