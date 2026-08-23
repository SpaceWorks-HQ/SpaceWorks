"""Key-free parent orchestration for the bounded Lane D DEK helper."""

import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from apps.backup.digests import sha256_file
from apps.encryption.cache import dek_cache_disabled

from .tenant_dump_dek_protocol import encode_helper_request
from .tenant_dump_errors import TenantDumpBuildError
from .tenant_dump_key_inventory import require_exact_retained_key_set


HELPER_MODULE = "apps.tenant_migration.tenant_dump_dek_helper"


def seal_tenant_deks(
    source_rows,
    retained_rows,
    tenant_dek_recipients,
    destination,
):
    """Seal exact retained rows without loading a plaintext DEK in this process."""
    with dek_cache_disabled():
        return _seal_tenant_deks(
            source_rows,
            retained_rows,
            tenant_dek_recipients,
            destination,
        )


def _seal_tenant_deks(
    source_rows,
    retained_rows,
    tenant_dek_recipients,
    destination,
):
    retained_rows = require_exact_retained_key_set(source_rows, retained_rows)
    request = encode_helper_request(retained_rows, tenant_dek_recipients)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        raise TenantDumpBuildError("The Lane D tenant DEK envelope already exists.")
    staging = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    process = None
    ciphertext = None
    failed = False
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", HELPER_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        ciphertext, _unused = process.communicate(request)
        if process.returncode != 0 or not ciphertext:
            raise OSError
        with staging.open("xb") as handle:
            if handle.write(ciphertext) != len(ciphertext):
                raise OSError
            handle.flush()
            os.fsync(handle.fileno())
        staging.chmod(0o600)
        os.replace(staging, destination)
        return {
            "path": "keys/tenant-deks.age",
            "size": destination.stat().st_size,
            "sha256": sha256_file(destination),
        }
    except Exception:
        failed = True
    finally:
        request = None
        ciphertext = None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()
        staging.unlink(missing_ok=True)
        if failed:
            destination.unlink(missing_ok=True)
    if failed:
        raise TenantDumpBuildError(
            "The retained tenant DEKs could not be sealed."
        )
