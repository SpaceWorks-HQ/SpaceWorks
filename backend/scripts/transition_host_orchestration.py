#!/usr/bin/env python3
"""Privileged H1a marker/grant transition primitive for the future supervisors."""

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

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
    OperationIdentity,
    marker_payload,
    read_marker,
    write_marker_fsynced,
)
from apps.backup.host_capability_journal import CapabilityJournal


def _arguments(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("state", choices=[state.value for state in MarkerState])
    parser.add_argument("--intent", action="store_true")
    parser.add_argument("--replace-database-identity", action="store_true")
    parser.add_argument("--readiness-json")
    parser.add_argument("--operation-json")
    parser.add_argument(
        "--capability-journal",
        default="/host-private/capability-journal.jsonl",
    )
    return parser.parse_args(argv)


def _credentials(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.username or parsed.password is None:
        raise RuntimeError("Runtime database URL must contain a PostgreSQL user and password.")
    return unquote(parsed.username), unquote(parsed.password)


def _readiness(path, current):
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        # Full marker parsing below is the single shape validator.
        return payload
    return {
        "reservations": list(current.reservations),
        "fences": list(current.fences),
        "not_restored": list(current.not_restored),
    }


def _operation(path, current):
    if not path:
        return current.operation
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Operation identity file must contain one JSON object.")
    try:
        return OperationIdentity(**payload)
    except TypeError as exc:
        raise RuntimeError("Operation identity file has an invalid shape.") from exc


def main(argv=None):
    args = _arguments(argv)
    if os.geteuid() != 0:
        raise RuntimeError("Host orchestration transition must run as root.")
    marker_path = Path(os.environ.get(
        "SPACEWORKS_HOST_MARKER_WRITE_PATH", "/host-state/restore-marker.json"
    ))
    current = read_marker(marker_path)
    capability_journal = CapabilityJournal(args.capability_journal)
    state = MarkerState(args.state)
    operation = _operation(args.operation_json, current)
    if args.intent and (
        state != MarkerState.CANDIDATE_PREPARATION
        or args.replace_database_identity
        or args.readiness_json
        or operation is None
    ):
        raise RuntimeError(
            "An intent transition requires candidate preparation and operation identity only."
        )
    if current.stage == MarkerStage.INTENT and current.operation != operation:
        raise RuntimeError("An existing intent belongs to a different operation.")
    if args.replace_database_identity and not args.readiness_json:
        raise RuntimeError("Replacing database identity requires explicit readiness facts.")
    runtime_url = os.environ.get("SPACEWORKS_RUNTIME_DATABASE_URL")
    if not runtime_url:
        raise RuntimeError("SPACEWORKS_RUNTIME_DATABASE_URL is required.")
    runtime_role, runtime_password = _credentials(runtime_url)
    # Invalidate before any marker effect. A crash here only narrows authority;
    # re-arming is an explicit supervisor operation and is never automatic.
    capability_journal.invalidate_all("marker-transition")
    if args.intent:
        write_marker_fsynced(
            marker_path,
            marker_payload(state, None, operation=operation),
        )
    with psycopg2.connect(os.environ["DATABASE_URL"]) as database:
        database.autocommit = True
        with database.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), oid FROM pg_database WHERE datname = current_database()"
            )
            name, oid = cursor.fetchone()
            try:
                live_identity = query_live_database_identity(database)
            except DatabaseIdentityError:
                live_identity = None
            identity = DatabaseIdentity(
                name=name,
                oid=oid,
                server_identity=(
                    live_identity.server_identity() if live_identity else None
                ),
            )
            same_database = current.database is not None and (
                current.database.name, current.database.oid
            ) == (identity.name, identity.oid)
            if args.intent:
                target = GrantTarget(database=name, runtime_role=runtime_role)
                fence_runtime_login(cursor, runtime_role)
                provision_runtime_role(cursor, target, runtime_password)
                apply_grant_state(cursor, target, state)
                return
            if current.stage == MarkerStage.INTENT and (
                not args.replace_database_identity
                or state != MarkerState.CANDIDATE_PREPARATION
            ):
                raise RuntimeError(
                    "Binding an intent requires explicit replacement in candidate preparation."
                )
            if not same_database and not args.replace_database_identity:
                raise RuntimeError("Live database identity differs; explicit replacement is required.")
            if (
                state == MarkerState.CANDIDATE_PREPARATION
                and current.state not in {
                    MarkerState.CANDIDATE_PREPARATION,
                    MarkerState.CANDIDATE_HEALTH,
                }
                and same_database
            ):
                raise RuntimeError("Candidate preparation requires a distinct sibling database.")
            target = GrantTarget(database=name, runtime_role=runtime_role)
            if state == MarkerState.CANDIDATE_PREPARATION:
                fence_runtime_login(cursor, runtime_role)
            provision_runtime_role(cursor, target, runtime_password)
            payload = marker_payload(
                state,
                identity,
                readiness=_readiness(args.readiness_json, current),
                operation=operation,
            )
            if state == MarkerState.CANDIDATE_HEALTH and (
                identity.server_identity is None or payload.get("operation") is None
            ):
                raise RuntimeError(
                    "Candidate health requires queried database and operation identities."
                )
            if state in {
                MarkerState.CANDIDATE_PREPARATION,
                MarkerState.QUARANTINED_AFTER_CUTOVER,
            }:
                write_marker_fsynced(marker_path, payload)
            apply_grant_state(cursor, target, state)
    if state not in {
        MarkerState.CANDIDATE_PREPARATION,
        MarkerState.QUARANTINED_AFTER_CUTOVER,
    }:
        write_marker_fsynced(marker_path, payload)


if __name__ == "__main__":
    main()
