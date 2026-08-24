"""Private host files built on H1's directory-fsync primitive."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from apps.backup.host_marker import MarkerError


def _fsync_directory(path):
    directory_fd = os.open(Path(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_private_file_fsynced(
    path, data, *, mode=0o600, require_root_owned=True
):
    if not isinstance(data, (str, bytes)) or mode & 0o077:
        raise MarkerError("Private host file payload or mode is invalid.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_stat = target.parent.stat(follow_symlinks=False)
    if require_root_owned and (
        os.geteuid() != 0
        or not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != 0
        or parent_stat.st_mode & 0o077
    ):
        raise MarkerError("Private host file parent is not root-owned and private.")
    if target.exists():
        target_stat = target.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(target_stat.st_mode)
            or (require_root_owned and target_stat.st_uid != 0)
            or target_stat.st_mode & 0o077
        ):
            raise MarkerError("Existing private host file is untrusted.")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            mode,
        )
        with os.fdopen(fd, "wb") as handle:
            encoded = data.encode("utf-8") if isinstance(data, str) else data
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, mode)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def unlink_private_file_fsynced(path):
    target = Path(path)
    if target.exists() and not stat.S_ISREG(target.stat(follow_symlinks=False).st_mode):
        raise MarkerError("Private host file removal target is untrusted.")
    target.unlink(missing_ok=True)
    _fsync_directory(target.parent)
