"""Package already-frozen object bytes without touching live object storage."""

import hashlib
from pathlib import Path, PurePosixPath
import shutil

from .tenant_dump_errors import TenantDumpVerificationError

_BUCKET_DIRECTORIES = {"private": "private", "public_image": "public"}


def package_staged_objects(staging_root, bundle_root, entries):
    """Copy immutable capture members and return the Lane D object manifest."""
    staging_root = Path(staging_root).resolve()
    bundle_root = Path(bundle_root)
    manifest = []
    for entry in entries:
        bucket_kind = entry["bucket_kind"]
        if bucket_kind not in _BUCKET_DIRECTORIES:
            raise TenantDumpVerificationError("Unknown Lane D object bucket kind.")
        original_key = entry.get(
            "original_key", entry.get("source_key", entry.get("key"))
        )
        if not isinstance(original_key, str) or not original_key:
            raise TenantDumpVerificationError("Lane D object is missing its original key.")
        opaque = hashlib.sha256(original_key.encode("utf-8")).hexdigest()
        member = PurePosixPath(
            "objects", _BUCKET_DIRECTORIES[bucket_kind], opaque
        )
        source_member = PurePosixPath(entry.get("member_path", str(member)))
        if source_member.is_absolute() or ".." in source_member.parts:
            raise TenantDumpVerificationError("Unsafe immutable object member path.")
        source = (staging_root / Path(*source_member.parts)).resolve()
        if staging_root not in source.parents:
            raise TenantDumpVerificationError("Immutable object member escaped staging.")
        destination = bundle_root / Path(*member.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, destination)
            destination.chmod(0o600)
        except OSError as exc:
            raise TenantDumpVerificationError(
                f"Immutable staged object is unavailable: {source_member}."
            ) from exc
        size, digest = _file_digest(destination)
        if size != int(entry["size"]) or digest != entry["sha256"]:
            raise TenantDumpVerificationError(
                f"Immutable staged object digest changed: {source_member}."
            )
        manifest.append(
            {
                "bucket_kind": bucket_kind,
                "member_path": str(member),
                "original_key": original_key,
                "version_id": entry.get("version_id") or None,
                "size": size,
                "content_type": entry.get("content_type") or "",
                "sha256": digest,
            }
        )
    return tuple(sorted(manifest, key=lambda item: item["member_path"]))


def _file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()
