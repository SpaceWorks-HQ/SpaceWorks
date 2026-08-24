"""Strict parsing and durable writes for the host-owned orchestration marker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
import stat
import uuid

from .host_marker_file import write_json_fsynced


MARKER_VERSION = 2
MAX_OID = (1 << 32) - 1
MAX_SYSTEM_IDENTIFIER = (1 << 64) - 1
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

class MarkerError(RuntimeError):
    pass

class MarkerState(StrEnum):
    NORMAL = "normal"
    CANDIDATE_PREPARATION = "candidate-preparation"
    CANDIDATE_HEALTH = "candidate-health"
    QUARANTINED_AFTER_CUTOVER = "quarantined-after-cutover"
    ACKNOWLEDGED_NORMAL = "acknowledged-normal"

class MarkerStage(StrEnum):
    INTENT = "intent"
    BOUND = "bound"

@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    name: str
    oid: int
    server_identity: dict | None = None

@dataclass(frozen=True, slots=True)
class OperationIdentity:
    restore_id: str
    artifact_sha256: str
    capture_id: str
    pointer_generation: int

@dataclass(frozen=True, slots=True)
class HostMarker:
    stage: MarkerStage
    state: MarkerState
    database: DatabaseIdentity | None
    database_routing: str | None
    reservations: tuple[dict, ...]
    fences: tuple[dict, ...]
    not_restored: tuple[dict, ...]
    operation: OperationIdentity | None = None

    def require_bound_database(self):
        if self.stage != MarkerStage.BOUND or self.database is None:
            raise MarkerError("Host marker database identity is not bound.")
        return self.database

def _identifier(value, label):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise MarkerError(f"Host marker {label} is not a safe PostgreSQL identifier.")
    return value

def _relation_check(item, label):
    required = {"schema", "table", "expected_rows", "sha256"}
    if not isinstance(item, dict) or set(item) != required:
        raise MarkerError(f"Host marker {label} entry has an invalid shape.")
    digest = item["sha256"]
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise MarkerError(f"Host marker {label}.sha256 is invalid.")
    return {
        "schema": _identifier(item["schema"], f"{label}.schema"),
        "table": _identifier(item["table"], f"{label}.table"),
        "expected_rows": _nonnegative_int(item["expected_rows"], f"{label}.expected_rows"),
        "sha256": digest,
    }

def _fence_check(item):
    required = {"schema", "table", "trigger", "enabled", "definition_sha256"}
    if not isinstance(item, dict) or set(item) != required or item["enabled"] is not True:
        raise MarkerError("Host marker fence entry has an invalid shape.")
    digest = item["definition_sha256"]
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise MarkerError("Host marker fence definition digest is invalid.")
    return {
        "schema": _identifier(item["schema"], "fences.schema"),
        "table": _identifier(item["table"], "fences.table"),
        "trigger": _identifier(item["trigger"], "fences.trigger"),
        "enabled": True,
        "definition_sha256": digest,
    }

def _nonnegative_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MarkerError(f"Host marker {label} must be a non-negative integer.")
    return value

def _positive_oid(value):
    value = _nonnegative_int(value, "database.oid")
    if not 0 < value <= MAX_OID:
        raise MarkerError("Host marker database OID is outside PostgreSQL's range.")
    return value

def _uuid(value, label):
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise MarkerError(f"Host marker {label} is not a UUID.") from exc
    return str(parsed)

def _server_identity(value):
    if not isinstance(value, dict) or set(value) != {
        "endpoint", "database_uuid", "system_identifier"
    }:
        raise MarkerError("Host marker server identity has an invalid shape.")
    endpoint = value["endpoint"]
    if not isinstance(endpoint, dict) or set(endpoint) != {
        "host", "port", "database", "tls_identity"
    }:
        raise MarkerError("Host marker database endpoint has an invalid shape.")
    if not all(isinstance(endpoint[key], str) for key in ("host", "database", "tls_identity")):
        raise MarkerError("Host marker database endpoint contains an invalid string.")
    if not endpoint["host"] or not endpoint["database"]:
        raise MarkerError("Host marker database endpoint is incomplete.")
    port = endpoint["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        raise MarkerError("Host marker database endpoint port is invalid.")
    system_identifier = value["system_identifier"]
    if system_identifier is not None and (
        not isinstance(system_identifier, str)
        or not system_identifier.isascii()
        or not system_identifier.isdecimal()
        or not 0 < int(system_identifier) <= MAX_SYSTEM_IDENTIFIER
    ):
        raise MarkerError("Host marker PostgreSQL system identifier is invalid.")
    return {
        "endpoint": dict(endpoint),
        "database_uuid": _uuid(value["database_uuid"], "database_uuid"),
        "system_identifier": system_identifier,
    }


def _operation(value):
    required = {"restore_id", "artifact_sha256", "capture_id", "pointer_generation"}
    if not isinstance(value, dict) or set(value) != required:
        raise MarkerError("Host marker operation identity has an invalid shape.")
    digest = value["artifact_sha256"]
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise MarkerError("Host marker artifact digest is invalid.")
    generation = value["pointer_generation"]
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise MarkerError("Host marker pointer generation is invalid.")
    return OperationIdentity(
        restore_id=_uuid(value["restore_id"], "restore_id"),
        artifact_sha256=digest,
        capture_id=_uuid(value["capture_id"], "capture_id"),
        pointer_generation=generation,
    )


def parse_marker(payload) -> HostMarker:
    if not isinstance(payload, dict) or set(payload) not in ({
        "version", "state", "database", "readiness"
    }, {"version", "state", "database", "readiness", "operation"}):
        raise MarkerError("Host marker has an invalid top-level shape.")
    if type(payload["version"]) is not int or payload["version"] != MARKER_VERSION:
        raise MarkerError("Host marker version is unsupported.")
    try:
        state = MarkerState(payload["state"])
    except (TypeError, ValueError) as exc:
        raise MarkerError("Host marker state is unknown.") from exc
    database_payload = payload["database"]
    if not isinstance(database_payload, dict) or "binding" not in database_payload:
        raise MarkerError("Host marker database identity has an invalid shape.")
    try:
        stage = MarkerStage(database_payload["binding"])
    except (TypeError, ValueError) as exc:
        raise MarkerError("Host marker database binding stage is unknown.") from exc
    database = None
    routing = None
    if stage == MarkerStage.INTENT:
        if set(database_payload) != {"binding"}:
            raise MarkerError("Host marker intent cannot carry database identity fields.")
    else:
        allowed = ({"binding", "name", "oid", "routing"},
                   {"binding", "name", "oid", "routing", "server_identity"})
        if set(database_payload) not in allowed:
            raise MarkerError("Host marker bound database identity has an invalid shape.")
        name = database_payload["name"]
        if not isinstance(name, str) or not name or "\x00" in name:
            raise MarkerError("Host marker database name is invalid.")
        routing = database_payload["routing"]
        expected = ("non-routable-sibling" if state in {
            MarkerState.CANDIDATE_PREPARATION, MarkerState.CANDIDATE_HEALTH
        } else "active")
        if routing != expected:
            raise MarkerError("Host marker database routing disagrees with its state.")
        server = (_server_identity(database_payload["server_identity"])
                  if "server_identity" in database_payload else None)
        if server is not None and server["endpoint"]["database"] != name:
            raise MarkerError("Host marker server identity names a different database.")
        database = DatabaseIdentity(name=name, oid=_positive_oid(database_payload["oid"]),
                                    server_identity=server)
    readiness = payload["readiness"]
    if not isinstance(readiness, dict) or set(readiness) != {
        "reservations", "fences", "not_restored"
    }:
        raise MarkerError("Host marker readiness declaration has an invalid shape.")
    if not all(isinstance(readiness[key], list) for key in readiness):
        raise MarkerError("Host marker readiness declarations must be lists.")
    operation = _operation(payload["operation"]) if "operation" in payload else None
    if stage == MarkerStage.INTENT and (
        state != MarkerState.CANDIDATE_PREPARATION or operation is None
    ):
        raise MarkerError("Host marker intent requires candidate preparation and operation identity.")
    return HostMarker(
        stage=stage, state=state,
        database=database,
        database_routing=routing,
        reservations=tuple(_relation_check(item, "reservations") for item in readiness["reservations"]),
        fences=tuple(_fence_check(item) for item in readiness["fences"]),
        not_restored=tuple(_relation_check(item, "not_restored") for item in readiness["not_restored"]),
        operation=operation,
    )


def _assert_trusted_file(path):
    try:
        file_stat = path.stat(follow_symlinks=False)
        directory_stat = path.parent.stat()
    except OSError as exc:
        raise MarkerError("Host marker is missing or unreadable.") from exc
    if not stat.S_ISREG(file_stat.st_mode) or stat.S_ISLNK(file_stat.st_mode):
        raise MarkerError("Host marker must be a regular non-symlink file.")
    if file_stat.st_uid != 0 or directory_stat.st_uid != 0:
        raise MarkerError("Host marker and directory must be root-owned.")
    if file_stat.st_mode & 0o022 or directory_stat.st_mode & 0o022:
        raise MarkerError("Host marker or directory is writable by a non-root principal.")


def read_marker(path, *, require_root_owned=True) -> HostMarker:
    path = Path(path)
    if require_root_owned:
        _assert_trusted_file(path)
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MarkerError("Host marker is missing, unreadable, or malformed.") from exc
    return parse_marker(payload)


def marker_payload(state, database, *, readiness=None, operation=None):
    state = MarkerState(state)
    if database is None and (
        state != MarkerState.CANDIDATE_PREPARATION or operation is None
    ):
        raise MarkerError("Host marker intent requires candidate preparation and operation identity.")
    payload = {
        "version": MARKER_VERSION,
        "state": state.value,
        "database": ({"binding": MarkerStage.INTENT.value} if database is None else {
            "binding": MarkerStage.BOUND.value,
            "name": database.name, "oid": database.oid,
            "routing": (
                "non-routable-sibling"
                if state in {MarkerState.CANDIDATE_PREPARATION, MarkerState.CANDIDATE_HEALTH}
                else "active"
            ),
        }),
        "readiness": (
            readiness
            if readiness is not None
            else {"reservations": [], "fences": [], "not_restored": []}
        ),
    }
    if database is not None and database.server_identity is not None:
        payload["database"]["server_identity"] = database.server_identity
    if operation is not None:
        payload["operation"] = {
            "restore_id": operation.restore_id,
            "artifact_sha256": operation.artifact_sha256,
            "capture_id": operation.capture_id,
            "pointer_generation": operation.pointer_generation,
        }
    return payload


def write_marker_fsynced(path, payload, *, crash_hook=None, require_root_owned=True):
    """Root-owned atomic replacement; the caller is the privileged host helper."""
    parse_marker(payload)
    write_json_fsynced(path, payload, crash_hook=crash_hook, require_root_owned=require_root_owned)
