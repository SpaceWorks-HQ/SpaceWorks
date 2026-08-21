"""Streamed integrity digests for backup bundles and encrypted archives."""

import hashlib
import hmac
from pathlib import Path, PurePosixPath


CHUNK_SIZE = 1024 * 1024
SUPPORTED_ARCHIVE_FORMATS = frozenset({
    "spaceworks-phase5a-v1",
    "spaceworks-phase5a-v2",
    "spaceworks-phase5a-v3",
})


class ArchiveDigestError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value):
    """Hash an in-memory archive member without first persisting it."""
    digest = hashlib.sha256()
    view = memoryview(value)
    for offset in range(0, len(view), CHUNK_SIZE):
        digest.update(view[offset : offset + CHUNK_SIZE])
    return digest.hexdigest()


def build_content_ledger(root):
    root = Path(root)
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        entries.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return entries


def verify_content_ledger(bundle_root, contents, *, require_ledger=False):
    if require_ledger and (not isinstance(contents, list) or not contents):
        raise ArchiveDigestError("Archive content ledger is required.")
    if not contents:
        return
    if not isinstance(contents, list):
        raise ArchiveDigestError("Archive content ledger is invalid.")
    root = Path(bundle_root).resolve()
    declared_paths = set()
    for entry in contents:
        relative = str(entry.get("path", "")) if isinstance(entry, dict) else ""
        pure_path = PurePosixPath(relative)
        if not relative or pure_path.is_absolute() or ".." in pure_path.parts:
            raise ArchiveDigestError(
                f"Archive content verification failed for {relative or '<missing path>'}."
            )
        normalized_relative = pure_path.as_posix()
        if normalized_relative in declared_paths:
            raise ArchiveDigestError(
                f"Archive content ledger contains duplicate path {relative}."
            )
        declared_paths.add(normalized_relative)
        path = root.joinpath(*pure_path.parts)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if path.is_symlink() or not resolved.is_file():
                raise OSError
            size = path.stat().st_size
            digest = sha256_file(path)
        except (OSError, ValueError) as exc:
            raise ArchiveDigestError(
                f"Archive content verification failed for {relative}."
            ) from exc
        expected_size = entry.get("size")
        expected_digest = entry.get("sha256")
        if (
            type(expected_size) is not int
            or size != expected_size
            or not isinstance(expected_digest, str)
            or not hmac.compare_digest(digest, expected_digest)
        ):
            raise ArchiveDigestError(
                f"Archive content verification failed for {relative}."
            )

    payload_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != "manifest.json"
    }
    unlisted_paths = payload_paths - declared_paths
    if unlisted_paths:
        raise ArchiveDigestError(
            "Archive content ledger does not list payload file(s): "
            + ", ".join(sorted(unlisted_paths))
            + "."
        )
