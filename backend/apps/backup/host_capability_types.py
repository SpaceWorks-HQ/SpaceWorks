"""Strict data contract for single-use host launch capabilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import uuid

from .host_marker import HostMarker, MAX_OID, MAX_SYSTEM_IDENTIFIER, MarkerError, MarkerState


SHA256 = re.compile(r"^[0-9a-f]{64}$")
NONCE = re.compile(r"^[0-9a-f]{64}$")
CAPABILITY_VERSION = 1


class CapabilityError(RuntimeError):
    pass


def canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        raise CapabilityError("Capability timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CapabilityError("Capability timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise CapabilityError("Capability timestamp lacks a timezone.")
    return parsed.astimezone(timezone.utc)


def timestamp_text(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def marker_binding(marker):
    operation = marker.operation
    try:
        database = marker.require_bound_database()
    except MarkerError as exc:
        raise CapabilityError("Launch capability requires a bound host marker.") from exc
    payload = {
        "stage": marker.stage.value,
        "state": marker.state.value,
        "database": {
            "name": database.name,
            "oid": database.oid,
            "server_identity": database.server_identity,
        },
        "operation": asdict(operation) if operation else None,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsumeRequest:
    role: str
    restore_id: str
    sibling_database_name: str
    sibling_database_oid: int
    server_identity: dict
    artifact_sha256: str
    capture_id: str

    def payload(self):
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    restore_id: str
    sibling_database_name: str
    sibling_database_oid: int
    server_identity: dict
    artifact_sha256: str
    capture_id: str
    nonce: str
    allowed_role: str
    expires_at: str
    marker_binding: str

    def payload(self):
        return asdict(self)

    def assert_matches(self, request, marker):
        try:
            database = marker.require_bound_database()
        except MarkerError as exc:
            raise CapabilityError("Launch capability requires a bound host marker.") from exc
        if marker.state != MarkerState.CANDIDATE_HEALTH or marker.operation is None:
            raise CapabilityError("Capability marker is not candidate health.")
        operation = marker.operation
        comparisons = (
            ("allowed role", self.allowed_role, request.role),
            ("restore ID", self.restore_id, operation.restore_id),
            ("sibling database name", self.sibling_database_name, database.name),
            ("sibling database OID", self.sibling_database_oid, database.oid),
            ("server identity", self.server_identity, database.server_identity),
            ("outer artifact digest", self.artifact_sha256, operation.artifact_sha256),
            ("capture ID", self.capture_id, operation.capture_id),
            ("restore ID", self.restore_id, request.restore_id),
            ("sibling database name", self.sibling_database_name, request.sibling_database_name),
            ("sibling database OID", self.sibling_database_oid, request.sibling_database_oid),
            ("server identity", self.server_identity, request.server_identity),
            ("outer artifact digest", self.artifact_sha256, request.artifact_sha256),
            ("capture ID", self.capture_id, request.capture_id),
            ("marker binding", self.marker_binding, marker_binding(marker)),
        )
        for label, expected, actual in comparisons:
            if expected != actual:
                raise CapabilityError(f"Capability {label} mismatch.")
        if timestamp(self.expires_at) <= utc_now():
            raise CapabilityError("Capability has expired.")


def record_from_marker(marker, *, allowed_role, expires_at, nonce=None):
    try:
        database = marker.require_bound_database()
    except MarkerError as exc:
        raise CapabilityError("Capabilities may be armed only from a bound marker.") from exc
    if marker.state != MarkerState.CANDIDATE_HEALTH:
        raise CapabilityError("Capabilities may be armed only for candidate health.")
    if marker.operation is None or database.server_identity is None:
        raise CapabilityError("The marker lacks operation or server identity facts.")
    operation = marker.operation
    return validate_record({
        "restore_id": operation.restore_id,
        "sibling_database_name": database.name,
        "sibling_database_oid": database.oid,
        "server_identity": database.server_identity,
        "artifact_sha256": operation.artifact_sha256,
        "capture_id": operation.capture_id,
        "nonce": nonce or secrets.token_hex(32),
        "allowed_role": allowed_role,
        "expires_at": timestamp_text(expires_at),
        "marker_binding": marker_binding(marker),
    })


def validate_request(value):
    required = set(ConsumeRequest.__dataclass_fields__)
    if not isinstance(value, dict) or set(value) != required:
        raise CapabilityError("Consume request has an invalid shape.")
    _validate_common(value)
    return ConsumeRequest(**value)


def validate_record(value):
    required = set(CapabilityRecord.__dataclass_fields__)
    if not isinstance(value, dict) or set(value) != required:
        raise CapabilityError("Capability record has an invalid shape.")
    _validate_common(value)
    if not isinstance(value["nonce"], str) or not NONCE.fullmatch(value["nonce"]):
        raise CapabilityError("Capability nonce is invalid.")
    if not isinstance(value["marker_binding"], str) or not SHA256.fullmatch(
        value["marker_binding"]
    ):
        raise CapabilityError("Capability marker binding is invalid.")
    timestamp(value["expires_at"])
    return CapabilityRecord(**value)


def _validate_common(value):
    for name in ("restore_id", "capture_id"):
        try:
            value[name] = str(uuid.UUID(value[name]))
        except (TypeError, ValueError, AttributeError) as exc:
            raise CapabilityError(f"Capability {name} is invalid.") from exc
    if not isinstance(value["artifact_sha256"], str) or not SHA256.fullmatch(
        value["artifact_sha256"]
    ):
        raise CapabilityError("Capability artifact digest is invalid.")
    for name in ("sibling_database_oid",):
        if (
            isinstance(value[name], bool)
            or not isinstance(value[name], int)
            or not 0 < value[name] <= MAX_OID
        ):
            raise CapabilityError(f"Capability {name} is invalid.")
    if not isinstance(value["sibling_database_name"], str) or not value["sibling_database_name"]:
        raise CapabilityError("Capability sibling database name is invalid.")
    if "role" in value and value["role"] != "backend":
        raise CapabilityError("Consume request role is not backend.")
    if "allowed_role" in value and value["allowed_role"] not in {
        "backend", "worker", "beat", "cron", "migrate", "management"
    }:
        raise CapabilityError("Capability allowed role is unknown.")
    server = value["server_identity"]
    if not isinstance(server, dict) or set(server) != {
        "endpoint", "database_uuid", "system_identifier"
    }:
        raise CapabilityError("Capability server identity is invalid.")
    endpoint = server["endpoint"]
    if not isinstance(endpoint, dict) or set(endpoint) != {
        "host", "port", "database", "tls_identity"
    }:
        raise CapabilityError("Capability database endpoint is invalid.")
    if not all(
        isinstance(endpoint[name], str)
        for name in ("host", "database", "tls_identity")
    ) or not endpoint["host"] or not endpoint["database"]:
        raise CapabilityError("Capability database endpoint is incomplete.")
    if endpoint["database"] != value["sibling_database_name"]:
        raise CapabilityError("Capability endpoint names a different database.")
    if (
        isinstance(endpoint["port"], bool)
        or not isinstance(endpoint["port"], int)
        or not 0 < endpoint["port"] < 65536
    ):
        raise CapabilityError("Capability database endpoint port is invalid.")
    try:
        server["database_uuid"] = str(uuid.UUID(server["database_uuid"]))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CapabilityError("Capability database UUID is invalid.") from exc
    system_identifier = server["system_identifier"]
    if system_identifier is not None and (
        not isinstance(system_identifier, str)
        or not system_identifier.isascii()
        or not system_identifier.isdecimal()
        or not 0 < int(system_identifier) <= MAX_SYSTEM_IDENTIFIER
    ):
        raise CapabilityError("Capability system identifier is invalid.")
