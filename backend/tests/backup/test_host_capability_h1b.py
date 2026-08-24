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
    validate_record,
    validate_request,
)
from apps.backup.host_launch_grant import (
    generate_launch_grant_keys,
    sign_launch_grant,
    verify_launch_grant,
)
from apps.backup.host_pointer import PointerRecord, write_pointer_atomic
from apps.backup.host_marker import (
    DatabaseIdentity,
    MarkerState,
    OperationIdentity,
    marker_payload,
    parse_marker,
)


def _marker():
    database_uuid = str(uuid.uuid4())
    server = {
        "endpoint": {
            "host": "candidate-db",
            "port": 5432,
            "database": "spaceworks_candidate",
            "tls_identity": "verify-full:sha256:" + "1" * 64,
        },
        "database_uuid": database_uuid,
        "system_identifier": "739201122334455",
    }
    return parse_marker(marker_payload(
        MarkerState.CANDIDATE_HEALTH,
        DatabaseIdentity("spaceworks_candidate", 8421, server),
        operation=OperationIdentity(
            restore_id=str(uuid.uuid4()),
            artifact_sha256="a" * 64,
            capture_id=str(uuid.uuid4()),
            pointer_generation=4,
        ),
    ))


def _record_and_request(marker, *, expires=None):
    record = record_from_marker(
        marker,
        allowed_role="backend",
        expires_at=expires or utc_now() + timedelta(minutes=1),
    )
    request = ConsumeRequest(
        role="backend",
        restore_id=record.restore_id,
        sibling_database_name=record.sibling_database_name,
        sibling_database_oid=record.sibling_database_oid,
        server_identity=record.server_identity,
        artifact_sha256=record.artifact_sha256,
        capture_id=record.capture_id,
    )
    return record, request


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("restore_id", lambda: str(uuid.uuid4()), "restore ID"),
        ("sibling_database_name", lambda: "wrong_candidate", "database name"),
        ("sibling_database_oid", lambda: 99, "database OID"),
        ("server_identity", lambda: {
            "endpoint": {"host": "wrong", "port": 5432, "database": "spaceworks_candidate", "tls_identity": ""},
            "database_uuid": str(uuid.uuid4()), "system_identifier": None,
        }, "server identity"),
        ("artifact_sha256", lambda: "b" * 64, "artifact digest"),
        ("capture_id", lambda: str(uuid.uuid4()), "capture ID"),
        ("allowed_role", lambda: "worker", "allowed role"),
    ],
)
def test_every_capability_fact_mismatch_refuses_independently(
    tmp_path, field, bad_value, message
):
    marker = _marker()
    record, request = _record_and_request(marker)
    payload = record.payload()
    payload[field] = bad_value()
    if field == "sibling_database_name":
        payload["server_identity"]["endpoint"]["database"] = payload[field]
    if field == "server_identity":
        payload[field]["endpoint"]["database"] = payload["sibling_database_name"]
    mismatched = validate_record(payload)
    journal = CapabilityJournal(tmp_path / "journal.jsonl", require_root_owned=False)
    journal.arm(mismatched)

    with pytest.raises(CapabilityError, match=message):
        journal.consume(request, marker)


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("restore_id", lambda: str(uuid.uuid4()), "restore ID"),
        ("sibling_database_name", lambda: "wrong_candidate", "database name"),
        ("sibling_database_oid", lambda: 99, "database OID"),
        ("server_identity", lambda: {
            "endpoint": {"host": "wrong", "port": 5432, "database": "spaceworks_candidate", "tls_identity": ""},
            "database_uuid": str(uuid.uuid4()), "system_identifier": None,
        }, "server identity"),
        ("artifact_sha256", lambda: "b" * 64, "artifact digest"),
        ("capture_id", lambda: str(uuid.uuid4()), "capture ID"),
    ],
)
def test_every_live_consume_fact_mismatch_refuses_independently(
    tmp_path, field, bad_value, message
):
    marker = _marker()
    record, request = _record_and_request(marker)
    payload = request.payload()
    payload[field] = bad_value()
    if field == "sibling_database_name":
        payload["server_identity"]["endpoint"]["database"] = payload[field]
    mismatched = validate_request(payload)
    journal = CapabilityJournal(tmp_path / "journal.jsonl", require_root_owned=False)
    journal.arm(record)

    with pytest.raises(CapabilityError, match=message):
        journal.consume(mismatched, marker)


def test_expired_capability_is_invalidated_and_refused(tmp_path):
    marker = _marker()
    record, request = _record_and_request(marker, expires=utc_now() - timedelta(seconds=1))
    journal = CapabilityJournal(tmp_path / "journal.jsonl", require_root_owned=False)
    journal.arm(record)

    with pytest.raises(CapabilityError, match="expired"):
        journal.consume(request, marker)

    assert journal.invalidate_expired() == 0


def test_consumption_is_single_use_and_rearm_is_explicit(tmp_path):
    marker = _marker()
    record, request = _record_and_request(marker)
    journal = CapabilityJournal(tmp_path / "journal.jsonl", require_root_owned=False)
    journal.arm(record)
    journal.consume(request, marker)  # Simulated crash before entrypoint exec.

    with pytest.raises(CapabilityError, match="already consumed"):
        journal.consume(request, marker)

    replacement = replace(record, nonce="f" * 64)
    journal.rearm(record.nonce, replacement)
    assert journal.consume(request, marker).nonce == replacement.nonce


def test_marker_terminal_and_pointer_events_invalidate_every_nonce(tmp_path):
    marker = _marker()
    for reason in ("marker-transition", "terminal-operation", "pointer-transition"):
        journal = CapabilityJournal(
            tmp_path / f"{reason}.jsonl", require_root_owned=False
        )
        record, request = _record_and_request(marker)
        journal.arm(record)
        assert journal.invalidate_all(reason) == 1
        with pytest.raises(CapabilityError, match="No launch capability"):
            journal.consume(request, marker)


def test_socket_invalidates_armed_nonce_when_pointer_generation_rolls_back(tmp_path):
    marker = _marker()
    record, request = _record_and_request(marker)
    journal = CapabilityJournal(tmp_path / "journal", require_root_owned=False)
    journal.arm(record)
    pointer = tmp_path / "database-pointer.env"
    write_pointer_atomic(
        pointer,
        PointerRecord("postgres://app@db/active", 3),
        require_root_owned=False,
    )
    server = CapabilitySocketServer(
        socket_path=tmp_path / "socket",
        journal=journal,
        marker_path=tmp_path / "marker",
        private_key_path=tmp_path / "private",
        public_key_path=tmp_path / "public",
        pointer_path=pointer,
        require_root_owned=False,
    )

    with pytest.raises(CapabilityError, match="generation"):
        server._assert_pointer_generation(marker)
    with pytest.raises(CapabilityError, match="No launch capability"):
        journal.consume(request, marker)


def test_grant_verifies_only_with_the_mounted_public_key(tmp_path):
    marker = _marker()
    record, request = _record_and_request(marker)
    private = tmp_path / "private.key"
    public = tmp_path / "public.key"
    wrong_private = tmp_path / "wrong-private.key"
    wrong_public = tmp_path / "wrong-public.key"
    generate_launch_grant_keys(private, public)
    generate_launch_grant_keys(wrong_private, wrong_public)
    grant = sign_launch_grant(
        record, request, private_key_path=private, public_key_path=public,
        require_root_owned=False,
    )

    assert verify_launch_grant(
        grant, request, public_key_path=public, require_root_owned=False
    )["nonce"] == record.nonce
    with pytest.raises(CapabilityError, match="signer"):
        verify_launch_grant(
            grant, request, public_key_path=wrong_public, require_root_owned=False
        )
    forged = json.loads(json.dumps(grant))
    forged["grant"]["nonce"] = "0" * 64
    with pytest.raises(CapabilityError, match="signature"):
        verify_launch_grant(
            forged, request, public_key_path=public, require_root_owned=False
        )


def test_socket_rejects_every_operation_except_consume(tmp_path, monkeypatch):
    marker = _marker()
    marker_path = tmp_path / "marker.json"
    marker_path.write_text(json.dumps(marker_payload(
        marker.state, marker.database, operation=marker.operation
    )), encoding="utf-8")
    server = CapabilitySocketServer(
        socket_path=tmp_path / "socket",
        journal=CapabilityJournal(tmp_path / "journal", require_root_owned=False),
        marker_path=marker_path,
        private_key_path=tmp_path / "private",
        public_key_path=tmp_path / "public",
        expected_peer_uid=10001,
        require_root_owned=False,
    )
    monkeypatch.setattr(server, "_peer_credentials", lambda _connection: (1, 10001, 10001))
    client, host = socket.socketpair()
    try:
        client.sendall(b'{"operation":"read-file","request":{}}\n')
        server.handle_connection(host)
        response = json.loads(client.recv(4096))
    finally:
        client.close()
        host.close()
    assert response == {"ok": False, "error": "Capability socket accepts only consume requests."}


def test_socket_rejects_an_unauthenticated_local_peer(tmp_path, monkeypatch):
    server = CapabilitySocketServer(
        socket_path=tmp_path / "socket",
        journal=CapabilityJournal(tmp_path / "journal", require_root_owned=False),
        marker_path=tmp_path / "marker",
        private_key_path=tmp_path / "private",
        public_key_path=tmp_path / "public",
        expected_peer_uid=10001,
        require_root_owned=False,
    )
    monkeypatch.setattr(server, "_peer_credentials", lambda _connection: (1, 9999, 9999))
    client, host = socket.socketpair()
    try:
        client.sendall(b'{"operation":"consume","request":{}}\n')
        server.handle_connection(host)
        response = json.loads(client.recv(4096))
    finally:
        client.close()
        host.close()
    assert response == {"ok": False, "error": "Capability socket peer is not authenticated."}
