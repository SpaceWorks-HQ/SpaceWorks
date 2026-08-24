"""Ownership markers and age-based cleanup for Lane D scratch databases."""

from contextlib import contextmanager
import json
import logging
import time
import uuid

from django.conf import settings
from django.db import connections

from apps.backup.postgres_client import client_binary, server_major


logger = logging.getLogger(__name__)
MARKER_KIND = "spaceworks-tenant-dump-database-v1"


@contextmanager
def _admin_connection(database):
    alias = f"tenant_dump_database_admin_{uuid.uuid4().hex}"
    connections.databases[alias] = {**database, "CONN_MAX_AGE": 0}
    try:
        yield connections[alias]
    finally:
        connections[alias].close()
        del connections.databases[alias]
        if hasattr(connections._connections, alias):
            delattr(connections._connections, alias)


def mark_owned_database(name, database):
    marker = json.dumps(
        {"kind": MARKER_KIND, "created_at": time.time()},
        sort_keys=True,
        separators=(",", ":"),
    )
    with _admin_connection(database) as connection, connection.cursor() as cursor:
        cursor.execute(f'COMMENT ON DATABASE "{name}" IS %s', [marker])


def sweep_stale_databases(*, now=None):
    database = getattr(
        settings, "TENANT_DUMP_SCRATCH_DATABASE", settings.DATABASES["default"]
    )
    cutoff = (now or time.time()) - int(
        getattr(settings, "TENANT_DUMP_STAGING_MAX_AGE_SECONDS", 7 * 24 * 60 * 60)
    )
    with _admin_connection(database) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT datname, shobj_description(oid, 'pg_database') "
            "FROM pg_database WHERE datname LIKE 'spaceworks_dump_%' ORDER BY datname"
        )
        rows = tuple(cursor.fetchall())
    removed = 0
    from .tenant_dump_database import _run

    major = server_major()
    for name, raw_marker in rows:
        try:
            marker = json.loads(raw_marker or "")
            owned = marker.get("kind") == MARKER_KIND
            stale = float(marker.get("created_at", 0)) < cutoff
        except (TypeError, ValueError):
            owned = stale = False
        if not (owned and stale):
            continue
        _run(
            [client_binary("dropdb", major), "--if-exists", name],
            database=database,
        )
        removed += 1
    return removed
