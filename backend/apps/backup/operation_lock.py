from contextlib import contextmanager
import fcntl
from pathlib import Path

from django.conf import settings


class OperationLockUnavailable(RuntimeError):
    pass


@contextmanager
def deployment_operation_lock(*, blocking=False):
    directory = Path(settings.BACKUP_OPS_DIR)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle = (directory / "operation.lock").open("a+")
    except OSError as exc:
        raise OperationLockUnavailable(
            "The shared host operation directory is unavailable; backup/restore cannot be fenced."
        ) from exc
    flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
    try:
        fcntl.flock(handle.fileno(), flags)
    except BlockingIOError as exc:
        handle.close()
        raise OperationLockUnavailable("Another deployment operation is already running.") from exc
    try:
        yield handle
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

