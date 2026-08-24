"""PostgreSQL-owned sequence high-water facts for Lane E readable mains."""

from django.db import connections

from apps.backup.recipient_selection import BackupBuildError


def sequence_facts(using):
    """Return collision-safe sequence facts without publishing individual row IDs."""

    connection = connections[using]
    facts = []
    with connection.cursor() as cursor:
        cursor.execute(_SEQUENCE_SQL)
        for row in cursor.fetchall():
            (
                schema, sequence, table, column, type_identity, increment,
                start, minimum, maximum, cycle, cache,
            ) = row
            quote = connection.ops.quote_name
            cursor.execute(
                f"SELECT last_value, is_called FROM {quote(schema)}.{quote(sequence)}"
            )
            last_value, is_called = cursor.fetchone()
            aggregate = "max" if increment > 0 else "min"
            cursor.execute(
                f"SELECT {aggregate}({quote(column)}) "
                f"FROM {quote(schema)}.{quote(table)}"
            )
            occupied_edge = cursor.fetchone()[0]
            safe_last = last_value
            if occupied_edge is not None:
                safe_last = (
                    max(last_value, occupied_edge)
                    if increment > 0
                    else min(last_value, occupied_edge)
                )
            if not minimum <= safe_last <= maximum:
                raise BackupBuildError(
                    f"Sequence {sequence} has no safe high-water value."
                )
            next_value = safe_last + increment
            if cycle or not minimum <= next_value <= maximum:
                raise BackupBuildError(
                    f"Sequence {sequence} cannot prove a collision-free next value."
                )
            facts.append({
                "schema": schema,
                "sequence": sequence,
                "table": table,
                "column": column,
                "type_identity": type_identity,
                "increment": increment,
                "start": start,
                "minimum": minimum,
                "maximum": maximum,
                "cycle": cycle,
                "cache": cache,
                "captured_last_value": last_value,
                "captured_is_called": is_called,
                "installed_last_value": safe_last,
                "installed_is_called": True,
                "next_generated_value": next_value,
            })
    return tuple(sorted(facts, key=lambda item: (item["schema"], item["sequence"])))


_SEQUENCE_SQL = """
SELECT seq_ns.nspname, seq.relname, tbl.relname, attr.attname,
       type_ns.nspname || '.' || typ.typname || ':' ||
           pg_catalog.format_type(attr.atttypid, attr.atttypmod),
       s.seqincrement, s.seqstart, s.seqmin, s.seqmax, s.seqcycle, s.seqcache
  FROM pg_catalog.pg_sequence s
  JOIN pg_catalog.pg_class seq ON seq.oid = s.seqrelid
  JOIN pg_catalog.pg_namespace seq_ns ON seq_ns.oid = seq.relnamespace
  JOIN pg_catalog.pg_depend dep ON dep.objid = seq.oid AND dep.deptype IN ('a', 'i')
  JOIN pg_catalog.pg_class tbl ON tbl.oid = dep.refobjid
  JOIN pg_catalog.pg_attribute attr
    ON attr.attrelid = tbl.oid AND attr.attnum = dep.refobjsubid
  JOIN pg_catalog.pg_type typ ON typ.oid = attr.atttypid
  JOIN pg_catalog.pg_namespace type_ns ON type_ns.oid = typ.typnamespace
 WHERE seq_ns.nspname = 'public'
 ORDER BY seq_ns.nspname, seq.relname
"""
