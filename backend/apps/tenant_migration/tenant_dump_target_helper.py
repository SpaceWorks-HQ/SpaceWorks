"""Short-lived target child for tenant identity proof and DEK installation."""

import base64
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import django

from .tenant_dump_dek_helper import PAYLOAD_MAGIC


def install_deks(request):
    """Stream records, exact-check them, and store only target-wrapped bytes."""
    from django.db import transaction

    from apps.audit import services as audit
    from apps.encryption.cache import dek_cache_disabled
    from apps.encryption.models import MakerspaceEncryptionKey
    from apps.makerspaces.models import Makerspace

    from .import_keys import install_streamed_deks
    from .target_state import IMPORTING
    from .tenant_dump_target_identities import _validated_identity_mount

    identities = []
    process = None
    versions = []
    try:
        mounted_paths = tuple(
            _validated_identity_mount(path, mountinfo_path="/proc/self/mountinfo")
            for path in request["identity_paths"]
        )
        identities = [path.open("rb", buffering=0) for path in mounted_paths]
        command = ["age", "-d"]
        for handle in identities:
            command.extend(("-i", f"/proc/self/fd/{handle.fileno()}"))
        with Path(request["envelope_path"]).open("rb", buffering=0) as ciphertext:
            process = subprocess.Popen(
                command,
                stdin=ciphertext,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                pass_fds=tuple(handle.fileno() for handle in identities),
                close_fds=True,
            )
            if process.stdout is None:
                raise OSError
            with dek_cache_disabled(), transaction.atomic():
                makerspace = Makerspace.objects.select_for_update().get(
                    pk=request["makerspace_id"], lifecycle_state=IMPORTING
                )
                _assert_derived_tables_empty()
                _require_bytes(process.stdout, PAYLOAD_MAGIC)
                count = struct.unpack(">I", _read_exact(process.stdout, 4))[0]
                if count != len(request["inventory"]):
                    raise ValueError
                versions = list(
                    install_streamed_deks(
                        makerspace,
                        _stream_records(process.stdout, request["inventory"]),
                        preserved_makerspace_id=request["makerspace_id"],
                    )
                )
                if process.stdout.read(1):
                    raise ValueError
                if process.wait() != 0:
                    raise ValueError
                if MakerspaceEncryptionKey.objects.filter(
                    makerspace=makerspace,
                    status=MakerspaceEncryptionKey.Status.ACTIVE,
                ).count() != 1:
                    raise ValueError
                audit.record(
                    None,
                    "tenant_migration.target_deks_installed",
                    makerspace=makerspace,
                    target=makerspace,
                    meta={
                        "versions": versions,
                        "broker_backend": MakerspaceEncryptionKey.objects.get(
                            makerspace=makerspace,
                            status=MakerspaceEncryptionKey.Status.ACTIVE,
                        ).broker_backend,
                    },
                )
        return {"installed_versions": versions}
    finally:
        if process is not None:
            _reap(process)
        for handle in identities:
            handle.close()


def decrypt_challenge(request):
    from .tenant_dump_target_identities import _validated_identity_mount

    ciphertext = _decode_unpadded(request["ciphertext"])
    identity = None
    process = None
    try:
        path = _validated_identity_mount(
            request["identity_path"], mountinfo_path="/proc/self/mountinfo"
        )
        identity = path.open("rb", buffering=0)
        process = subprocess.Popen(
            ["age", "-d", "-i", f"/proc/self/fd/{identity.fileno()}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            pass_fds=(identity.fileno(),),
            close_fds=True,
        )
        plaintext, _unused = process.communicate(ciphertext)
        if process.returncode != 0 or not plaintext:
            raise ValueError
        return {"submitted_nonce": plaintext.decode("ascii")}
    finally:
        if process is not None:
            _reap(process)
        if identity is not None:
            identity.close()


def _assert_derived_tables_empty():
    from apps.encryption.models import (
        MakerspaceEncryptionKey,
        PiiBlindIndex,
        SearchKeyGeneration,
    )

    if (
        MakerspaceEncryptionKey.objects.exists()
        or PiiBlindIndex.objects.exists()
        or SearchKeyGeneration.objects.exists()
    ):
        raise ValueError


def _stream_records(handle, inventory):
    for expected in inventory:
        dek = None
        try:
            owner, version = struct.unpack(">QI", _read_exact(handle, 12))
            status_length = struct.unpack(">H", _read_exact(handle, 2))[0]
            if status_length < 1 or status_length > 16:
                raise ValueError
            status = _read_exact(handle, status_length).decode("ascii")
            dek_length = struct.unpack(">H", _read_exact(handle, 2))[0]
            if dek_length != 32:
                raise ValueError
            dek = _read_exact(handle, dek_length)
            if (owner, version, status) != (
                expected["makerspace_id"],
                expected["version"],
                expected["status"],
            ):
                raise ValueError
            yield {"version": version, "status": status, "dek": dek}
        finally:
            dek = None


def _read_exact(handle, size):
    chunks = bytearray()
    while len(chunks) < size:
        value = handle.read(size - len(chunks))
        if not value:
            raise ValueError
        chunks.extend(value)
    return bytes(chunks)


def _require_bytes(handle, expected):
    if _read_exact(handle, len(expected)) != expected:
        raise ValueError


def _decode_unpadded(value):
    return base64.b64decode(
        value + ("=" * (-len(value) % 4)), altchars=b"-_", validate=True
    )


def _reap(process):
    if process.poll() is None:
        process.kill()
    process.wait()
    for stream in (process.stdin, process.stdout):
        if stream is not None and not stream.closed:
            stream.close()


def main():
    _disable_core_dumps_best_effort()
    django.setup()
    from .tenant_dump_target_protocol import (
        CHALLENGE_PROTOCOL,
        INSTALL_PROTOCOL,
        decode_request,
    )

    try:
        protocol, request = decode_request(sys.stdin.buffer.read())
        if protocol == INSTALL_PROTOCOL:
            result = install_deks(request)
        elif protocol == CHALLENGE_PROTOCOL:
            result = decrypt_challenge(request)
        else:
            raise ValueError
        sys.stdout.buffer.write(
            (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1


def _disable_core_dumps_best_effort():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, OSError, ValueError):
        return


if __name__ == "__main__":
    os._exit(main())
