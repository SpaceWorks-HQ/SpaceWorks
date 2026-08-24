from contextlib import contextmanager

from django.db import connection, connections, transaction

from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable


# PostgreSQL advisory locks are keyed by a pair of signed int32 values. These values
# are deliberately outside the PII namespaces (734201/734202); the import fence uses
# the PII operation setting rather than this namespace.
SOURCE_GATE_LOCK_NAMESPACE = 734_310
UNSCOPED_WRITER_LOCK_KEY = 0


def acquire_shared(makerspace_id):
    _execute_transaction("pg_advisory_xact_lock_shared", makerspace_id)


def acquire_exclusive(makerspace_id):
    _execute_transaction("pg_advisory_xact_lock", makerspace_id)


def acquire_unscoped_writer_shared():
    _execute_transaction(
        "pg_advisory_xact_lock_shared", UNSCOPED_WRITER_LOCK_KEY
    )


def acquire_unscoped_writer_exclusive():
    _execute_transaction("pg_advisory_xact_lock", UNSCOPED_WRITER_LOCK_KEY)


def try_acquire_exclusive(makerspace_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            [SOURCE_GATE_LOCK_NAMESPACE, int(makerspace_id)],
        )
        return bool(cursor.fetchone()[0])


def _execute_transaction(function, makerspace_id):
    if not connection.in_atomic_block:
        raise RuntimeError("Source migration locks require an atomic transaction.")
    _execute(function, makerspace_id)


def _execute(function, makerspace_id):
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {function}(%s, %s)",
            [SOURCE_GATE_LOCK_NAMESPACE, int(makerspace_id)],
        )


@contextmanager
def shared_boundary(makerspace_id):
    """Hold one shared-lock reference without transacting on the caller connection."""
    lock = _BoundarySharedLock(makerspace_id)
    try:
        lock.acquire()
        yield lock
    finally:
        lock.release()


class _BoundarySharedLock:
    """One idempotent reference held by a dedicated lock-only transaction."""

    def __init__(self, makerspace_id):
        self.makerspace_id = int(makerspace_id)
        self.acquired = False
        self.lock_connection = None

    def acquire(self):
        if self.acquired:
            return
        lock_connection = None
        try:
            lock_connection = _new_lock_connection()
            self.lock_connection = lock_connection
            lock_connection.ensure_connection()
            lock_connection.set_autocommit(False)
            with lock_connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pg_advisory_xact_lock_shared(%s, %s),
                           pg_backend_pid()
                    """,
                    [SOURCE_GATE_LOCK_NAMESPACE, self.makerspace_id],
                )
                lock_backend_pid = cursor.fetchone()[1]
                cursor.execute(
                    """
                    SELECT pg_backend_pid(), EXISTS (
                        SELECT 1 FROM pg_locks
                        WHERE locktype = 'advisory'
                          AND pid = pg_backend_pid()
                          AND classid = %s AND objid = %s
                          AND granted
                    )
                    """,
                    [SOURCE_GATE_LOCK_NAMESPACE, self.makerspace_id],
                )
                retained_backend_pid, lock_is_held = cursor.fetchone()
                if retained_backend_pid != lock_backend_pid or not lock_is_held:
                    raise RuntimeError("The shared advisory lock was not retained.")
            self.acquired = True
        except Exception as exc:
            if lock_connection is not None:
                try:
                    lock_connection.close()
                except Exception:
                    pass
            self.lock_connection = None
            raise SourceMigrationGateUnavailable(
                "The source migration write gate is unavailable."
            ) from exc

    def release(self):
        if not self.acquired:
            return
        lock_connection = self.lock_connection
        release_error = None
        try:
            lock_connection.rollback()
        except Exception as exc:
            release_error = exc
        try:
            lock_connection.close()
        except Exception as exc:
            release_error = release_error or exc
        finally:
            self.lock_connection = None
            self.acquired = False
        if release_error is not None:
            raise SourceMigrationGateUnavailable(
                "The source migration write gate could not be released safely."
            ) from release_error


def _new_lock_connection():
    return connections["default"].copy(alias="source_migration_gate_lock")


@contextmanager
def unscoped_writer_shared_boundary():
    with shared_boundary(UNSCOPED_WRITER_LOCK_KEY):
        yield


@contextmanager
def shared_transaction(makerspace_id):
    with transaction.atomic():
        acquire_shared(makerspace_id)
        yield
