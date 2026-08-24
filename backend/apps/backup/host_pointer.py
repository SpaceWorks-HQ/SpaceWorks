"""Atomic Compose pointer records and external store-native CAS contract."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Protocol


POINTER_KEYS = ("DATABASE_URL", "SPACEWORKS_DB_POINTER_GENERATION")


class PointerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PointerRecord:
    database_url: str
    generation: int


@dataclass(frozen=True, slots=True)
class VersionedPointer:
    record: PointerRecord
    store_version: str


class AtomicPointerStore(Protocol):
    supports_compare_and_swap: bool

    def read(self) -> VersionedPointer: ...

    def compare_and_swap(
        self, expected_version: str, record: PointerRecord
    ) -> VersionedPointer: ...


def pointer_text(record):
    record = validate_pointer(record)
    if any(character in record.database_url for character in ("\n", "\r", "'")):
        raise PointerError("Database pointer URL cannot be safely encoded.")
    return (
        f"DATABASE_URL='{record.database_url}'\n"
        f"SPACEWORKS_DB_POINTER_GENERATION={record.generation}\n"
    )


def parse_pointer_text(value):
    assignments = {}
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PointerError("Database pointer contains an invalid assignment.")
        key, item = line.split("=", 1)
        if key in assignments:
            raise PointerError("Database pointer contains a duplicate assignment.")
        if key == POINTER_KEYS[0]:
            if item.startswith("'") or item.endswith("'"):
                if len(item) < 2 or not (item.startswith("'") and item.endswith("'")):
                    raise PointerError("Database pointer URL quoting is invalid.")
                item = item[1:-1]
            elif "$" in item:
                raise PointerError("Database pointer URL must prevent interpolation.")
        assignments[key] = item
    if tuple(assignments) != POINTER_KEYS:
        raise PointerError("Database pointer must contain URL then generation only.")
    try:
        generation = int(assignments[POINTER_KEYS[1]])
    except ValueError as exc:
        raise PointerError("Database pointer generation is invalid.") from exc
    return validate_pointer(PointerRecord(assignments[POINTER_KEYS[0]], generation))


def validate_pointer(record):
    if not isinstance(record, PointerRecord):
        raise PointerError("Database pointer record is invalid.")
    if not isinstance(record.database_url, str) or not record.database_url:
        raise PointerError("Database pointer URL is missing.")
    if isinstance(record.generation, bool) or not isinstance(record.generation, int) or record.generation < 1:
        raise PointerError("Database pointer generation must be positive.")
    return record


def read_pointer(path, *, require_root_owned=True):
    path = Path(path)
    try:
        file_stat = path.stat(follow_symlinks=False)
        parent_stat = path.parent.stat()
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PointerError("Database pointer is missing or unreadable.") from exc
    if require_root_owned and (
        file_stat.st_uid != 0
        or parent_stat.st_uid != 0
        or file_stat.st_mode & 0o027
        or parent_stat.st_mode & 0o027
        or not stat.S_ISREG(file_stat.st_mode)
    ):
        raise PointerError("Database pointer or parent directory is misowned.")
    return parse_pointer_text(value)


def write_pointer_atomic(
    path,
    record,
    *,
    expected_generation=None,
    invalidate=None,
    crash_hook=None,
    require_root_owned=True,
):
    record = validate_pointer(record)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing_stat = None
    if target.exists():
        current = read_pointer(target, require_root_owned=require_root_owned)
        existing_stat = target.stat(follow_symlinks=False)
        if expected_generation is None or current.generation != expected_generation:
            raise PointerError("Database pointer expected generation is stale.")
        if record.generation <= current.generation:
            raise PointerError("Database pointer generation must increase monotonically.")
        if invalidate is None:
            raise PointerError("Pointer transition requires capability invalidation.")
    elif expected_generation is not None:
        raise PointerError("Database pointer expected generation is stale.")
    if require_root_owned and (
        os.geteuid() != 0
        or target.parent.stat().st_uid != 0
        or target.parent.stat().st_mode & 0o027
    ):
        raise PointerError("Database pointer parent directory is not root-owned.")
    if invalidate is not None:
        invalidate("pointer-transition")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
        )
        if existing_stat is not None:
            os.fchown(fd, existing_stat.st_uid, existing_stat.st_gid)
            os.fchmod(fd, stat.S_IMODE(existing_stat.st_mode))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(pointer_text(record))
            handle.flush()
            os.fsync(handle.fileno())
        _hook(crash_hook, "before_replace")
        os.replace(temporary, target)
        _hook(crash_hook, "after_replace")
        _hook(crash_hook, "before_parent_fsync")
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        _hook(crash_hook, "after_parent_fsync")
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return record


def compare_and_swap_external(store, *, expected_version, record, invalidate=None):
    if not getattr(store, "supports_compare_and_swap", False):
        raise PointerError("External pointer store lacks native compare-and-swap.")
    current = store.read()
    if current.store_version != expected_version:
        raise PointerError("External pointer expected version is stale.")
    record = validate_pointer(record)
    if record.generation <= current.record.generation:
        raise PointerError("External pointer generation must increase monotonically.")
    if invalidate is None:
        raise PointerError("External pointer transition requires capability invalidation.")
    invalidate("pointer-transition")
    result = store.compare_and_swap(expected_version, record)
    if result.record != record:
        raise PointerError("External pointer store returned a different committed record.")
    return result


def _hook(callback, stage):
    if callback is not None:
        callback(stage)
