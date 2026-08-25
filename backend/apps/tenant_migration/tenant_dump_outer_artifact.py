"""Canonical readable wrapper for one sealed Lane D payload."""

import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tarfile
from uuid import uuid4

from .tenant_dump_errors import TenantDumpBuildError, TenantDumpVerificationError
from .tenant_dump_outer_manifest import canonical_manifest_bytes
from .tenant_dump_outer_manifest_validation import PAYLOAD_MEMBER


OUTER_MANIFEST_MEMBER = "outer-manifest.json"
OUTER_MEMBERS = (OUTER_MANIFEST_MEMBER, PAYLOAD_MEMBER)
MAX_OUTER_MANIFEST_BYTES = 64 * 1024
_BLOCK = tarfile.BLOCKSIZE
_RECORD = tarfile.RECORDSIZE


def write_outer_artifact(payload, destination, manifest):
    """Atomically write the only accepted readable Lane D wrapper shape."""
    payload = Path(payload)
    destination = Path(destination)
    if destination.exists():
        raise TenantDumpBuildError("The Lane D outer artifact already exists.")
    manifest_bytes = canonical_manifest_bytes(manifest)
    staging = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with tarfile.open(staging, "x", format=tarfile.USTAR_FORMAT) as archive:
            archive.addfile(
                _member_info(OUTER_MANIFEST_MEMBER, len(manifest_bytes)),
                io.BytesIO(manifest_bytes),
            )
            with payload.open("rb") as handle:
                archive.addfile(
                    _member_info(PAYLOAD_MEMBER, payload.stat().st_size), handle
                )
        staging.chmod(0o600)
        os.replace(staging, destination)
    except (OSError, tarfile.TarError) as exc:
        staging.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise TenantDumpBuildError(
            "The Lane D readable outer artifact could not be written."
        ) from exc
    return destination


def read_outer_manifest(artifact):
    """Validate the readable structure and ciphertext binding without decryption."""
    artifact = Path(artifact)
    try:
        with tarfile.open(artifact, "r:") as archive:
            members = archive.getmembers()
            if [member.name for member in members] != list(OUTER_MEMBERS):
                raise ValueError
            if any(not member.isreg() for member in members):
                raise ValueError
            manifest_member, payload_member = members
            if not 0 < manifest_member.size <= MAX_OUTER_MANIFEST_BYTES:
                raise ValueError
            manifest_handle = archive.extractfile(manifest_member)
            if manifest_handle is None:
                raise ValueError
            manifest_bytes = manifest_handle.read(MAX_OUTER_MANIFEST_BYTES + 1)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            canonical = canonical_manifest_bytes(manifest)
            if not hmac.compare_digest(manifest_bytes, canonical):
                raise ValueError
            fact = manifest["encrypted_members"][0]
            if payload_member.size != fact["size"]:
                raise ValueError
            _verify_canonical_tar(artifact, members, manifest_bytes)
            payload_handle = archive.extractfile(payload_member)
            if payload_handle is None:
                raise ValueError
            digest = hashlib.sha256()
            while chunk := payload_handle.read(1024 * 1024):
                digest.update(chunk)
            if not hmac.compare_digest(digest.hexdigest(), fact["sha256"]):
                raise ValueError
    except (
        KeyError,
        OSError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        tarfile.TarError,
    ) as exc:
        raise TenantDumpVerificationError(
            "The Lane D readable outer artifact is invalid or is not bound to its sealed payload."
        ) from exc
    return manifest


def _verify_canonical_tar(artifact, members, manifest_bytes):
    manifest_member, payload_member = members
    expected_payload_offset = _BLOCK + _padded_size(len(manifest_bytes)) + _BLOCK
    expected_size = _archive_size(len(manifest_bytes), payload_member.size)
    if (
        manifest_member.offset != 0
        or manifest_member.offset_data != _BLOCK
        or payload_member.offset_data != expected_payload_offset
        or Path(artifact).stat().st_size != expected_size
    ):
        raise ValueError
    with Path(artifact).open("rb") as handle:
        if handle.read(_BLOCK) != _member_info(
            OUTER_MANIFEST_MEMBER, len(manifest_bytes)
        ).tobuf(format=tarfile.USTAR_FORMAT):
            raise ValueError
        handle.seek(payload_member.offset)
        if handle.read(_BLOCK) != _member_info(
            PAYLOAD_MEMBER, payload_member.size
        ).tobuf(format=tarfile.USTAR_FORMAT):
            raise ValueError
        handle.seek(_BLOCK + len(manifest_bytes))
        if any(handle.read(_padded_size(len(manifest_bytes)) - len(manifest_bytes))):
            raise ValueError
        handle.seek(payload_member.offset_data + payload_member.size)
        if any(handle.read(expected_size - handle.tell())):
            raise ValueError


def _member_info(name, size):
    member = tarfile.TarInfo(name)
    member.size = size
    member.mode = 0o600
    member.mtime = 0
    member.uid = 0
    member.gid = 0
    member.uname = ""
    member.gname = ""
    return member


def _padded_size(size):
    return ((size + _BLOCK - 1) // _BLOCK) * _BLOCK


def _archive_size(manifest_size, payload_size):
    used = (
        _BLOCK
        + _padded_size(manifest_size)
        + _BLOCK
        + _padded_size(payload_size)
        + 2 * _BLOCK
    )
    return ((used + _RECORD - 1) // _RECORD) * _RECORD
