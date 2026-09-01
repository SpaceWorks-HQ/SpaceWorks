"""Narrow consume-only Unix socket shared by host supervisor and entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import struct

from .host_capability_types import CapabilityError, canonical_json, validate_request
from .host_launch_grant import sign_launch_grant, verify_launch_grant
from .host_marker import MarkerError, read_marker
from .host_pointer import PointerError, read_pointer


MAX_REQUEST_BYTES = 64 * 1024
DEFAULT_SOCKET_PATH = "/run/spaceworks-host/capability.sock"
DEFAULT_PUBLIC_KEY_PATH = "/run/spaceworks-host/launch-grant-public.key"
DEFAULT_POINTER_PATH = "/var/lib/spaceworks/ops/database-pointer.env"


class CapabilitySocketServer:
    def __init__(
        self,
        *,
        socket_path,
        journal,
        marker_path,
        private_key_path,
        public_key_path,
        pointer_path=DEFAULT_POINTER_PATH,
        expected_peer_uid=10001,
        require_root_owned=True,
    ):
        self.socket_path = Path(socket_path)
        self.journal = journal
        self.marker_path = marker_path
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path
        self.pointer_path = pointer_path
        self.expected_peer_uid = expected_peer_uid
        self.require_root_owned = require_root_owned

    def serve_forever(self):
        if self.require_root_owned and os.geteuid() != 0:
            raise CapabilityError("Capability socket server must run as root.")
        with self._listener() as listener:
            listener.settimeout(1)
            while True:
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    self.journal.invalidate_expired()
                    continue
                with connection:
                    self.handle_connection(connection)

    def handle_connection(self, connection):
        try:
            _pid, uid, _gid = self._peer_credentials(connection)
            if uid != self.expected_peer_uid:
                raise CapabilityError("Capability socket peer is not authenticated.")
            document = self._read_document(connection)
            if not isinstance(document, dict) or set(document) != {"operation", "request"}:
                raise CapabilityError("Capability socket request has an invalid shape.")
            if document["operation"] != "consume":
                raise CapabilityError("Capability socket accepts only consume requests.")
            request = validate_request(document["request"])
            marker = read_marker(
                self.marker_path,
                require_root_owned=self.require_root_owned,
            )
            try:
                marker.require_bound_database()
            except MarkerError as exc:
                raise CapabilityError(
                    "Launch capability refused: host marker database identity is not bound."
                ) from exc
            self._assert_pointer_generation(marker)
            record = self.journal.consume(request, marker)
            grant = sign_launch_grant(
                record,
                request,
                private_key_path=self.private_key_path,
                public_key_path=self.public_key_path,
                require_root_owned=self.require_root_owned,
            )
            response = {"ok": True, "launch_grant": grant}
        except (CapabilityError, MarkerError) as exc:
            response = {"ok": False, "error": str(exc)}
        connection.sendall(canonical_json(response) + b"\n")

    def _assert_pointer_generation(self, marker):
        try:
            pointer = read_pointer(
                self.pointer_path,
                require_root_owned=self.require_root_owned,
            )
        except PointerError as exc:
            self.journal.invalidate_all("pointer-unavailable")
            raise CapabilityError("Database pointer could not be verified.") from exc
        if marker.operation is None or (
            marker.operation.pointer_generation != pointer.generation
        ):
            self.journal.invalidate_all("pointer-rollback-or-drift")
            raise CapabilityError("Database pointer generation disagrees with the marker.")

    @staticmethod
    def _peer_credentials(connection):
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        return struct.unpack("3i", raw)

    @staticmethod
    def _read_document(connection):
        payload = bytearray()
        while b"\n" not in payload:
            chunk = connection.recv(min(4096, MAX_REQUEST_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_REQUEST_BYTES:
                raise CapabilityError("Capability socket request is too large.")
        line, separator, remainder = bytes(payload).partition(b"\n")
        if not separator or remainder:
            raise CapabilityError("Capability socket accepts exactly one JSON request.")
        try:
            return json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CapabilityError("Capability socket request is malformed.") from exc

    def _listener(self):
        parent = self.socket_path.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        if self.require_root_owned:
            parent_stat = parent.stat()
            if parent_stat.st_uid != 0 or parent_stat.st_mode & 0o022:
                raise CapabilityError("Capability socket directory is misowned.")
        if self.socket_path.exists() or self.socket_path.is_socket():
            existing = self.socket_path.stat(follow_symlinks=False)
            if not stat.S_ISSOCK(existing.st_mode) or (
                self.require_root_owned and existing.st_uid != 0
            ):
                raise CapabilityError("Refusing to replace an untrusted socket path.")
            self.socket_path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_path))
        os.chown(self.socket_path, 0, self.expected_peer_uid)
        os.chmod(self.socket_path, 0o660)
        listener.listen(8)
        return listener


def request_signed_launch_grant(
    request,
    *,
    socket_path=DEFAULT_SOCKET_PATH,
    public_key_path=DEFAULT_PUBLIC_KEY_PATH,
    require_root_owned=True,
):
    request = validate_request(request.payload() if hasattr(request, "payload") else request)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(socket_path))
        client.sendall(canonical_json({
            "operation": "consume",
            "request": request.payload(),
        }) + b"\n")
        response = CapabilitySocketServer._read_document(client)
    if not isinstance(response, dict) or set(response) not in (
        {"ok", "launch_grant"}, {"ok", "error"}
    ):
        raise CapabilityError("Capability socket response has an invalid shape.")
    if response["ok"] is not True:
        raise CapabilityError(response.get("error", "Capability was refused."))
    return verify_launch_grant(
        response["launch_grant"],
        request,
        public_key_path=public_key_path,
        require_root_owned=require_root_owned,
    )
