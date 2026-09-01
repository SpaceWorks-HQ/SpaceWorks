#!/usr/bin/env python3
"""Privileged one-shot used by bundled topologies to provision grants and marker."""

import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlparse
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backup.database_grants import (
    GrantTarget,
    apply_grant_state,
    fence_runtime_login,
    provision_runtime_role,
)
from apps.backup.database_identity import (
    DatabaseIdentityError,
    query_live_database_identity,
)
from apps.backup.host_marker import (
    DatabaseIdentity,
    MarkerStage,
    MarkerState,
    marker_payload,
    read_marker,
    write_marker_fsynced,
)
from apps.backup.topology import validate_scheduler_environment


def _runtime_credentials(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.username or parsed.password is None:
        raise RuntimeError("Runtime database URL must contain a PostgreSQL user and password.")
    return unquote(parsed.username), unquote(parsed.password)


def _database_url(url, database_name):
    parsed = urlsplit(url)
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        "/" + quote(database_name, safe=""),
        parsed.query,
        "",
    ))


def _grant_only(maintenance_url, runtime_url):
    database_name = os.environ.get("SPACEWORKS_GRANT_DATABASE_NAME", "")
    if database_name:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,62}", database_name):
            raise RuntimeError("Grant target database name is invalid.")
        maintenance_url = _database_url(maintenance_url, database_name)
        runtime_url = _database_url(runtime_url, database_name)
    runtime_role, runtime_password = _runtime_credentials(runtime_url)
    try:
        with psycopg2.connect(maintenance_url) as database:
            database.autocommit = True
            with database.cursor() as cursor:
                cursor.execute("SELECT current_database()")
                live_name = cursor.fetchone()[0]
                target = GrantTarget(database=live_name, runtime_role=runtime_role)
                provision_runtime_role(cursor, target, runtime_password)
                apply_grant_state(cursor, target, MarkerState.NORMAL)
    except Exception:
        # DSNs contain credentials. Do not let a driver exception echo them into
        # the host log; callers need only the stable failure classification.
        raise RuntimeError("Role/grant reprovisioning failed.") from None


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Host orchestration bootstrap must run as root.")
    maintenance_url = os.environ["DATABASE_URL"]
    runtime_url = os.environ.get("SPACEWORKS_RUNTIME_DATABASE_URL")
    if not runtime_url:
        raise RuntimeError("SPACEWORKS_RUNTIME_DATABASE_URL is required.")
    if os.environ.get("SPACEWORKS_GRANTS_ONLY") == "1":
        _grant_only(maintenance_url, runtime_url)
        return
    validate_scheduler_environment({
        "SPACEWORKS_SCHEDULER_MODE": os.environ.get("SPACEWORKS_SCHEDULER_MODE", ""),
        "SPACEWORKS_SCHEDULER_SERVICES": os.environ.get("SPACEWORKS_SCHEDULER_SERVICES", ""),
        "SPACEWORKS_SCHEDULER_HOST_GATE_COMMAND": os.environ.get(
            "SPACEWORKS_SCHEDULER_HOST_GATE_COMMAND", ""
        ),
        "SPACEWORKS_SCHEDULER_CONTROL_PLANE_DISABLEMENT": os.environ.get(
            "SPACEWORKS_SCHEDULER_CONTROL_PLANE_DISABLEMENT", ""
        ),
    })
    marker_path = os.environ.get(
        "SPACEWORKS_HOST_MARKER_WRITE_PATH", "/host-state/restore-marker.json"
    )
    marker_file = Path(marker_path)
    existing_marker = read_marker(marker_file) if marker_file.exists() else None
    if existing_marker is not None and existing_marker.stage == MarkerStage.INTENT:
        raise RuntimeError(
            "Host marker intent cannot adopt a database; a new empty sibling is required."
        )
    runtime_role, runtime_password = _runtime_credentials(runtime_url)
    with psycopg2.connect(maintenance_url) as database:
        database.autocommit = True
        with database.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), oid FROM pg_database WHERE datname = current_database()"
            )
            name, oid = cursor.fetchone()
            try:
                live_identity = query_live_database_identity(database)
            except DatabaseIdentityError:
                # The first bootstrap runs before migration 0021. The second
                # upgrades the marker to the queried UUID before services start.
                live_identity = None
            identity = DatabaseIdentity(
                name=name,
                oid=oid,
                server_identity=(
                    live_identity.server_identity() if live_identity else None
                ),
            )
            target = GrantTarget(database=name, runtime_role=runtime_role)
            if existing_marker is not None:
                marker = existing_marker
                if (marker.database.name, marker.database.oid) != (name, oid):
                    raise RuntimeError("Existing host marker names a different live database.")
                state = marker.state
            else:
                state = MarkerState.NORMAL
            if state == MarkerState.CANDIDATE_PREPARATION:
                fence_runtime_login(cursor, runtime_role)
            provision_runtime_role(cursor, target, runtime_password)
            apply_grant_state(cursor, target, state)
    marker_file = Path(marker_path)
    if not marker_file.exists():
        write_marker_fsynced(marker_path, marker_payload(state, identity))
    elif state == MarkerState.NORMAL and identity.server_identity is not None:
        current = read_marker(marker_file)
        if current.database.server_identity is None:
            write_marker_fsynced(
                marker_path,
                marker_payload(state, identity, readiness={
                    "reservations": list(current.reservations),
                    "fences": list(current.fences),
                    "not_restored": list(current.not_restored),
                }),
            )


if __name__ == "__main__":
    main()
