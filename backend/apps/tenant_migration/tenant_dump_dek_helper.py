"""Short-lived child process that unwraps and pipes retained DEKs into age."""

import os
import struct
import subprocess
import sys

import django


PAYLOAD_MAGIC = b"spaceworks-tenant-deks-v1\n"


def age_command(tenant_dek_recipients):
    command = ["age"]
    for recipient in tenant_dek_recipients:
        command.extend(("-r", recipient))
    return command


def stream_envelope(rows, tenant_dek_recipients, output):
    """Write one age ciphertext; plaintext exists only in this child operation."""
    from apps.encryption import services
    from apps.encryption.cache import dek_cache_disabled

    process = None
    failed = False
    try:
        process = subprocess.Popen(
            age_command(tenant_dek_recipients),
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        if process.stdin is None:
            raise OSError
        with dek_cache_disabled():
            _write(process.stdin, PAYLOAD_MAGIC)
            _write(process.stdin, struct.pack(">I", len(rows)))
            for row in rows:
                dek = None
                row_failed = False
                try:
                    broker = services.broker_for_backend(row.broker_backend)
                    dek = broker.unwrap_dek(
                        row.wrapped_dek, row.makerspace_id, row.version
                    )
                    if not isinstance(dek, bytes) or len(dek) != 32:
                        raise ValueError
                    _write_record(process.stdin, row, dek)
                except Exception:
                    row_failed = True
                finally:
                    dek = None
                if row_failed:
                    raise RuntimeError
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError
    except Exception:
        failed = True
    finally:
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait()
    return 1 if failed else 0


def _write_record(handle, row, dek):
    status = row.status.encode("ascii")
    _write(handle, struct.pack(">QI", row.makerspace_id, row.version))
    _write(handle, struct.pack(">H", len(status)))
    _write(handle, status)
    _write(handle, struct.pack(">H", len(dek)))
    _write(handle, dek)


def _write(handle, payload):
    remaining = memoryview(payload)
    while remaining:
        written = handle.write(remaining)
        if type(written) is not int or written <= 0:
            raise OSError
        remaining = remaining[written:]


def main():
    # This is defense in depth only; it does not strengthen the bounded
    # application-level retention claim documented in INVARIANTS.md.
    _disable_core_dumps_best_effort()
    django.setup()
    from .tenant_dump_dek_protocol import decode_helper_request

    failed = False
    try:
        rows, recipients = decode_helper_request(sys.stdin.buffer.read())
        return stream_envelope(rows, recipients, sys.stdout.buffer)
    except Exception:
        failed = True
    return 1 if failed else 0


def _disable_core_dumps_best_effort():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, OSError, ValueError):
        return


if __name__ == "__main__":
    os._exit(main())
