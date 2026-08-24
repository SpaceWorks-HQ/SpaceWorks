"""Allowlisted payload ledger and readable outer envelope for Lane D."""

import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
from uuid import uuid4

from apps.backup.digests import sha256_file

from .tenant_dump_errors import TenantDumpBuildError, TenantDumpVerificationError
from .tenant_dump_outer_artifact import (
    read_outer_manifest,  # noqa: F401  public pre-decryption reader
    write_outer_artifact,  # noqa: F401  public canonical wrapper writer
)
from .tenant_dump_outer_manifest import (
    build_outer_manifest,  # noqa: F401  public builder retained here
)
from .tenant_dump_outer_manifest_facts import encrypted_member_fact
from .tenant_dump_outer_manifest_validation import (
    FORMAT,
    VERSION,
    validate_outer_manifest,  # noqa: F401  public structural validator
)


TENANT_DEKS_MEMBER = "keys/tenant-deks.age"
INNER_MANIFEST_MEMBER = "manifest.json"
DATABASE_MEMBER = "database.dump"
_OBJECT_SCOPES = frozenset({"private", "public"})


def build_tenant_content_ledger(bundle, *, source_pii_mode):
    """Declare every permitted payload member and the plaintext-mode absence."""
    contents, _paths = _content_ledger(
        bundle, source_pii_mode=source_pii_mode, allow_inner_manifest=False
    )
    return contents


def outer_age_command(outer_recipients, destination):
    command = ["age"]
    for recipient in outer_recipients:
        command.extend(("-r", recipient))
    command.extend(("-o", str(destination)))
    return command


def seal_outer_bundle(
    bundle,
    destination,
    outer_recipients,
    *,
    artifact_id,
    capture_id,
    outer_recipient_fingerprints,
    tenant_dek_recipient_fingerprints,
    source_build,
    postgres_major,
    compatibility,
):
    """Seal the inner bundle, then wrap it with a readable digest-bound manifest."""
    bundle = Path(bundle)
    destination = Path(destination)
    if destination.exists():
        raise TenantDumpBuildError("The Lane D outer artifact already exists.")
    paths = _verified_sealing_paths(bundle)
    payload = destination.with_name(f".{destination.name}.{uuid4().hex}.payload.age")
    process = None
    failed = False
    try:
        process = subprocess.Popen(
            outer_age_command(tuple(outer_recipients), payload),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        if process.stdin is None:
            raise OSError
        with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
            for path in paths:
                archive.add(
                    path,
                    arcname=path.relative_to(bundle).as_posix(),
                    recursive=False,
                )
        process.stdin.close()
        if process.wait() != 0 or not payload.is_file() or payload.stat().st_size <= 0:
            raise OSError
        manifest = build_outer_manifest(
            format=FORMAT,
            version=VERSION,
            artifact_id=artifact_id,
            capture_id=capture_id,
            outer_recipient_fingerprints=outer_recipient_fingerprints,
            tenant_dek_recipient_fingerprints=tenant_dek_recipient_fingerprints,
            encrypted_members=[encrypted_member_fact(payload)],
            source_build=source_build,
            postgres_major=postgres_major,
            compatibility=compatibility,
        )
        write_outer_artifact(payload, destination, manifest)
        read_outer_manifest(destination)
        return destination, sha256_file(destination)
    except TenantDumpVerificationError:
        failed = True
        raise
    except Exception:
        failed = True
    finally:
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait()
        payload.unlink(missing_ok=True)
        if failed:
            destination.unlink(missing_ok=True)
    if failed:
        raise TenantDumpBuildError("The Lane D outer bundle could not be sealed.")


def _verified_sealing_paths(bundle):
    manifest_path = Path(bundle, INNER_MANIFEST_MEMBER)
    try:
        if not stat.S_ISREG(manifest_path.lstat().st_mode):
            raise OSError
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_pii_mode = manifest["source_pii_mode"]
        expected = manifest["contents"]
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TenantDumpVerificationError(
            "The Lane D inner manifest is unavailable before sealing."
        ) from exc
    actual, paths = _content_ledger(
        bundle, source_pii_mode=source_pii_mode, allow_inner_manifest=True
    )
    if actual != expected:
        raise TenantDumpVerificationError(
            "The Lane D content ledger changed before sealing."
        )
    return paths


def _content_ledger(bundle, *, source_pii_mode, allow_inner_manifest):
    bundle = Path(bundle)
    contents = []
    paths = []
    for path in sorted(bundle.rglob("*")):
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise TenantDumpVerificationError(
                "A Lane D bundle member could not be inspected."
            ) from exc
        if not stat.S_ISREG(mode):
            continue
        relative = path.relative_to(bundle).as_posix()
        _require_allowed_member(relative, allow_inner_manifest=allow_inner_manifest)
        paths.append(path)
        if relative != INNER_MANIFEST_MEMBER:
            contents.append({
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "present": True,
            })
    key_entries = [entry for entry in contents if entry["path"] == TENANT_DEKS_MEMBER]
    if not any(entry["path"] == DATABASE_MEMBER for entry in contents):
        raise TenantDumpVerificationError(
            "The Lane D bundle lacks its required database.dump member."
        )
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
    return sorted(contents, key=lambda entry: entry["path"]), paths


def _require_allowed_member(relative, *, allow_inner_manifest):
    if relative == DATABASE_MEMBER or (
        allow_inner_manifest and relative == INNER_MANIFEST_MEMBER
    ) or relative == TENANT_DEKS_MEMBER:
        return
    parts = PurePosixPath(relative).parts
    if (
        len(parts) == 3
        and parts[0] == "objects"
        and parts[1] in _OBJECT_SCOPES
        and len(parts[2]) == 64
        and all(character in "0123456789abcdef" for character in parts[2])
    ):
        return
    raise TenantDumpVerificationError(
        f"Lane D bundle member is not permitted: {relative}."
    )
