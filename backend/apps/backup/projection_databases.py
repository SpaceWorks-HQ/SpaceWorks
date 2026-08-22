"""Short-lived PostgreSQL databases used to derive and verify readable mains."""

from contextlib import contextmanager
import logging
import subprocess
import uuid

from django.conf import settings
from django.db import connections

from apps.backup.archive_payload import _postgres_environment
from apps.backup.postgres_client import (
    PostgresClientUnavailable,
    client_binary,
    server_major,
)
from apps.backup.recipient_selection import BackupBuildError

logger = logging.getLogger(__name__)


def _client(tool, major=None):
    """Resolve a client binary, as a backup build failure when it is missing."""
    try:
        return client_binary(tool, major)
    except PostgresClientUnavailable as exc:
        raise BackupBuildError(str(exc)) from exc


def _run(command):
    """Run a PostgreSQL client command, logging the real failure before raising.

    The raised message stays generic because it reaches operators through the
    backup UI; the tool's own stderr goes to the log so a failure is diagnosable
    instead of anonymous.
    """
    try:
        subprocess.run(
            command,
            env=_postgres_environment(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        logger.error(
            "backup.projection_database_command_failed command=%s rc=%s stderr=%s",
            command[0],
            exc.returncode,
            (exc.stderr or b"").decode("utf-8", "replace")[-4000:],
        )
        raise BackupBuildError(
            "The readable-main verification database operation failed."
        ) from exc
    except OSError as exc:
        logger.error(
            "backup.projection_database_command_unavailable",
            extra={"command": command[0], "error": str(exc)},
        )
        raise BackupBuildError(
            "The readable-main verification database operation failed."
        ) from exc


@contextmanager
def temporary_database(role):
    name = f"spaceworks_backup_{role}_{uuid.uuid4().hex}"[:63]
    alias = f"backup_{role}_{uuid.uuid4().hex}"
    major = server_major()
    _run([_client("createdb", major), name])
    connections.databases[alias] = {
        **settings.DATABASES["default"],
        "NAME": name,
        "CONN_MAX_AGE": 0,
    }
    try:
        yield alias, name
    finally:
        connection = connections[alias]
        connection.close()
        del connections.databases[alias]
        if hasattr(connections._connections, alias):
            delattr(connections._connections, alias)
        _run([_client("dropdb", major), "--if-exists", name])


def restore_dump(path, database_name):
    _run([
        _client("pg_restore"),
        "--exit-on-error",
        "--no-owner",
        "--no-acl",
        f"--dbname={database_name}",
        str(path),
    ])


def dump_database(database_name, destination):
    _run([
        _client("pg_dump"),
        "--format=custom",
        "--no-owner",
        "--no-acl",
        f"--dbname={database_name}",
        f"--file={destination}",
    ])
