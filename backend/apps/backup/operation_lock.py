from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

class OperationLockUnavailable(RuntimeError):
    pass


@contextmanager
def host_operation_lock(directory, *, blocking=False, require_root_owned=False):
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            directory / "operation.lock",
            os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
            0o600,
        )
        handle = os.fdopen(fd, "a+")
    except OSError as exc:
        raise OperationLockUnavailable(
            "The shared host operation directory is unavailable; backup/restore cannot be fenced."
        ) from exc
    if require_root_owned and (
        os.geteuid() != 0
        or os.fstat(handle.fileno()).st_uid != 0
        or directory.stat().st_uid != 0
        or directory.stat().st_mode & 0o022
    ):
        handle.close()
        raise OperationLockUnavailable("The host operation lock is not root-owned.")
    flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
    try:
        fcntl.flock(handle.fileno(), flags)
    except BlockingIOError as exc:
        handle.close()
        raise OperationLockUnavailable(
            "Another deployment operation is already running."
        ) from exc
    try:
        yield handle
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


@contextmanager
def deployment_operation_lock(*, blocking=False):
    from django.conf import settings

    work_directory = Path(settings.BACKUP_OPS_DIR)
    lock_directory = (
        work_directory.parent
        if work_directory.name == "work" else work_directory
    )
    with host_operation_lock(lock_directory, blocking=blocking) as handle:
        yield handle
