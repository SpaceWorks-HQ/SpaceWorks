"""Atomic filesystem primitive for the public host-marker API."""

import json
import os
from pathlib import Path


def write_json_fsynced(
    path, payload, *, crash_hook=None, require_root_owned=True
):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if require_root_owned:
        os.chown(target.parent, 0, 0)
    os.chmod(target.parent, 0o755)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o444
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _hook(crash_hook, "before_replace")
        os.replace(temporary, target)
        _hook(crash_hook, "after_replace")
        os.chmod(target, 0o444)
        _hook(crash_hook, "before_parent_fsync")
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        _hook(crash_hook, "after_parent_fsync")
    finally:
        temporary.unlink(missing_ok=True)


def _hook(callback, stage):
    if callback is not None:
        callback(stage)
