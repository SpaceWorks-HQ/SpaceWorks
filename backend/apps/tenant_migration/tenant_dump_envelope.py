"""Content ledger and streaming outer age envelope for Lane D."""

import os
from pathlib import Path
import subprocess
import tarfile
from uuid import uuid4

from apps.backup.digests import build_content_ledger, sha256_file

from .tenant_dump_errors import TenantDumpBuildError, TenantDumpVerificationError


TENANT_DEKS_MEMBER = "keys/tenant-deks.age"


def build_tenant_content_ledger(bundle, *, source_pii_mode):
    """Declare every payload member, including the required plaintext-mode absence."""
    contents = [dict(entry, present=True) for entry in build_content_ledger(bundle)]
    key_entries = [entry for entry in contents if entry["path"] == TENANT_DEKS_MEMBER]
    if source_pii_mode == "plaintext":
        if key_entries:
            raise TenantDumpVerificationError(
                "A plaintext Lane D bundle contains a tenant DEK envelope."
            )
        contents.append({"path": TENANT_DEKS_MEMBER, "present": False})
    elif source_pii_mode == "encrypted":
        if len(key_entries) != 1:
            raise TenantDumpVerificationError(
                "An encrypted Lane D bundle lacks its one tenant DEK envelope."
            )
    else:
        raise TenantDumpVerificationError("The Lane D source PII mode is invalid.")
    return sorted(contents, key=lambda entry: entry["path"])


def outer_age_command(outer_recipients, destination):
    command = ["age"]
    for recipient in outer_recipients:
        command.extend(("-r", recipient))
    command.extend(("-o", str(destination)))
    return command


def seal_outer_bundle(bundle, destination, outer_recipients):
    """Stream the sanitized bundle into one age envelope without a plaintext tar."""
    bundle = Path(bundle)
    destination = Path(destination)
    if destination.exists():
        raise TenantDumpBuildError("The Lane D outer envelope already exists.")
    staging = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    process = None
    failed = False
    try:
        process = subprocess.Popen(
            outer_age_command(tuple(outer_recipients), staging),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        if process.stdin is None:
            raise OSError
        with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
            for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
                archive.add(
                    path,
                    arcname=path.relative_to(bundle).as_posix(),
                    recursive=False,
                )
        process.stdin.close()
        if process.wait() != 0:
            raise OSError
        if not staging.is_file() or staging.stat().st_size <= 0:
            raise OSError
        staging.chmod(0o600)
        os.replace(staging, destination)
        return destination, sha256_file(destination)
    except Exception:
        failed = True
    finally:
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait()
        staging.unlink(missing_ok=True)
        if failed:
            destination.unlink(missing_ok=True)
    if failed:
        raise TenantDumpBuildError("The Lane D outer bundle could not be sealed.")
