from contextlib import contextmanager

from django.db import connection, transaction


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


def _release_session_shared(makerspace_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock_shared(%s, %s)",
            [SOURCE_GATE_LOCK_NAMESPACE, int(makerspace_id)],
        )
        return bool(cursor.fetchone()[0])


@contextmanager
def shared_session(makerspace_id):
    """Hold one reference-counted session lock and always release that reference."""
    lock = _SessionSharedLock(makerspace_id)
    try:
        lock.acquire()
        yield lock
    finally:
        lock.release()


class _SessionSharedLock:
    """One session-lock reference whose release operation is idempotent."""

    def __init__(self, makerspace_id):
        self.makerspace_id = int(makerspace_id)
        self.acquired = False
        self.database_session = None

    def acquire(self):
        if self.acquired:
            return
        _execute("pg_advisory_lock_shared", self.makerspace_id)
        self.database_session = connection.connection
        self.acquired = True

    def release(self):
        if not self.acquired:
            return
        try:
            # Closing a database connection releases all of that session's advisory
            # locks. Never issue the matching unlock on a replacement session: it
            # could consume a reference acquired independently on that connection.
            if connection.connection is self.database_session:
                if not _release_session_shared(self.makerspace_id):
                    connection.close()
                    raise RuntimeError(
                        "The source migration session-lock reference was lost."
                    )
        except Exception:
            # If PostgreSQL could not execute the unlock, closing the owning session
            # is the only reliable way to release every advisory lock it still owns.
            if connection.connection is self.database_session:
                connection.close()
            raise
        finally:
            self.database_session = None
            self.acquired = False


@contextmanager
def unscoped_writer_shared_session():
    with shared_session(UNSCOPED_WRITER_LOCK_KEY):
        yield


@contextmanager
def shared_transaction(makerspace_id):
    with transaction.atomic():
        acquire_shared(makerspace_id)
        yield
