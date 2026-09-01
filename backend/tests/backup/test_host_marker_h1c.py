from dataclasses import replace
from datetime import timedelta
import json
import socket
import uuid

import pytest

from apps.backup.host_capability_journal import CapabilityJournal
from apps.backup.host_capability_socket import CapabilitySocketServer
from apps.backup.host_capability_types import (
    CapabilityError,
    ConsumeRequest,
    record_from_marker,
    utc_now,
)
from apps.backup.host_launch_grant import generate_launch_grant_keys
from apps.backup.host_marker import (
    MARKER_VERSION,
    DatabaseIdentity,
    MarkerError,
    MarkerStage,
    MarkerState,
    OperationIdentity,
    marker_payload,
    parse_marker,
    read_marker,
)
from apps.backup.host_pointer import PointerRecord, write_pointer_atomic
from apps.backup.host_supervisor import HostMarkerTransition


def _operation():
    return OperationIdentity(
        restore_id=str(uuid.uuid4()),
        artifact_sha256="a" * 64,
        capture_id=str(uuid.uuid4()),
        pointer_generation=4,
    )


def _bound_marker(operation=None):
    operation = operation or _operation()
    server = {
        "endpoint": {
            "host": "candidate-db",
            "port": 5432,
            "database": "candidate",
            "tls_identity": "",
        },
        "database_uuid": str(uuid.uuid4()),
        "system_identifier": None,
    }
    return parse_marker(marker_payload(
        MarkerState.CANDIDATE_HEALTH,
        DatabaseIdentity("candidate", 8421, server),
        operation=operation,
    ))


def _record_request(marker):
    record = record_from_marker(
        marker,
        allowed_role="backend",
        expires_at=utc_now() + timedelta(minutes=1),
    )
    return record, ConsumeRequest(
        role="backend",
        restore_id=record.restore_id,
        sibling_database_name=record.sibling_database_name,
        sibling_database_oid=record.sibling_database_oid,
        server_identity=record.server_identity,
        artifact_sha256=record.artifact_sha256,
        capture_id=record.capture_id,
    )


def _exchange(server, request, monkeypatch):
    monkeypatch.setattr(
        server, "_peer_credentials", lambda _connection: (1, 10001, 10001)
    )
    client, host = socket.socketpair()
    try:
        client.sendall(json.dumps({
            "operation": "consume", "request": request.payload()
        }).encode("utf-8") + b"\n")
        server.handle_connection(host)
        return json.loads(client.recv(65536))
    finally:
        client.close()
        host.close()


def test_intent_marker_round_trips_without_database_identity():
    operation = _operation()
    payload = marker_payload(
        MarkerState.CANDIDATE_PREPARATION, None, operation=operation
    )

    marker = parse_marker(payload)

    assert marker.stage == MarkerStage.INTENT
    assert marker.database is None
    assert marker.operation == operation
    assert payload["database"] == {"binding": "intent"}
    assert "name" not in json.dumps(payload["database"])
    assert "oid" not in json.dumps(payload["database"])


@pytest.mark.parametrize("missing", ["name", "oid"])
def test_half_bound_marker_is_refused_as_malformed(missing):
    payload = marker_payload(MarkerState.NORMAL, DatabaseIdentity("active", 42))
    payload["database"].pop(missing)

    with pytest.raises(MarkerError, match="invalid shape"):
        parse_marker(payload)


def test_unknown_marker_version_is_refused():
    payload = marker_payload(MarkerState.NORMAL, DatabaseIdentity("active", 42))
    payload["version"] = MARKER_VERSION + 1

    with pytest.raises(MarkerError, match="version is unsupported"):
        parse_marker(payload)


def test_intent_consume_refuses_without_spending_nonce_or_issuing_grant(
    tmp_path, monkeypatch
):
    bound = _bound_marker()
    record, request = _record_request(bound)
    journal = CapabilityJournal(tmp_path / "journal", require_root_owned=False)
    journal.arm(record)
    marker_path = tmp_path / "marker.json"
    marker_path.write_text(json.dumps(marker_payload(
        MarkerState.CANDIDATE_PREPARATION,
        None,
        operation=bound.operation,
    )), encoding="utf-8")
    server = CapabilitySocketServer(
        socket_path=tmp_path / "socket",
        journal=journal,
        marker_path=marker_path,
        private_key_path=tmp_path / "missing-private",
        public_key_path=tmp_path / "missing-public",
        pointer_path=tmp_path / "missing-pointer",
        require_root_owned=False,
    )

    response = _exchange(server, request, monkeypatch)

    assert response == {
        "ok": False,
        "error": "Launch capability refused: host marker database identity is not bound.",
    }
    assert "launch_grant" not in response
    assert journal.consume(request, bound).nonce == record.nonce


def test_bound_marker_consume_still_returns_a_signed_grant(tmp_path, monkeypatch):
    marker = _bound_marker()
    record, request = _record_request(marker)
    journal = CapabilityJournal(tmp_path / "journal", require_root_owned=False)
    journal.arm(record)
    marker_path = tmp_path / "marker.json"
    marker_path.write_text(json.dumps(marker_payload(
        marker.state, marker.database, operation=marker.operation
    )), encoding="utf-8")
    pointer = tmp_path / "pointer.env"
    write_pointer_atomic(
        pointer,
        PointerRecord("postgres://runtime@candidate-db/candidate", 4),
        require_root_owned=False,
    )
    private, public = tmp_path / "private", tmp_path / "public"
    generate_launch_grant_keys(private, public)
    server = CapabilitySocketServer(
        socket_path=tmp_path / "socket",
        journal=journal,
        marker_path=marker_path,
        private_key_path=private,
        public_key_path=public,
        pointer_path=pointer,
        require_root_owned=False,
    )

    response = _exchange(server, request, monkeypatch)

    assert response["ok"] is True
    assert response["launch_grant"]["grant"]["nonce"] == record.nonce


def test_intent_to_bound_transition_invalidates_outstanding_nonce(tmp_path):
    health = _bound_marker()
    record, request = _record_request(health)
    journal = CapabilityJournal(tmp_path / "journal", require_root_owned=False)
    journal.arm(record)
    marker_path = tmp_path / "marker.json"
    marker_path.write_text(json.dumps(marker_payload(
        health.state, health.database, operation=health.operation
    )), encoding="utf-8")
    transition = HostMarkerTransition(
        marker_path, journal, require_root_owned=False
    )
    transition.write_intent(health.operation)
    replacement = replace(record, nonce="f" * 64)
    journal.rearm(record.nonce, replacement)

    transition.bind_database(DatabaseIdentity("candidate", 8422), health.operation)

    with pytest.raises(CapabilityError, match="No launch capability is armed"):
        journal.consume(request, health)


def test_bound_rename_before_parent_fsync_leaves_only_a_complete_marker(tmp_path):
    marker_path = tmp_path / "marker.json"
    operation = _operation()
    journal = CapabilityJournal(tmp_path / "journal", require_root_owned=False)
    transition = HostMarkerTransition(
        marker_path, journal, require_root_owned=False
    )
    transition.write_intent(operation)

    def crash(stage):
        if stage == "before_parent_fsync":
            raise RuntimeError("simulated crash after rename")

    crashing = HostMarkerTransition(
        marker_path, journal, require_root_owned=False, crash_hook=crash
    )
    with pytest.raises(RuntimeError, match="after rename"):
        crashing.bind_database(DatabaseIdentity("candidate", 8421), operation)

    marker = read_marker(marker_path, require_root_owned=False)
    assert marker.stage == MarkerStage.BOUND
    assert marker.require_bound_database() == DatabaseIdentity("candidate", 8421)
