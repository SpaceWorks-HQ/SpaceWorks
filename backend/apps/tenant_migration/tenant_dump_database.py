"""Owned PostgreSQL databases used by the Lane D scratch lifecycle."""

from contextlib import contextmanager
import hashlib
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlencode

from django.conf import settings
from django.db import connections

from apps.backup.postgres_client import client_binary, server_major

from .tenant_dump_errors import TenantDumpBuildError

logger = logging.getLogger(__name__)
_SAFE_NAME = re.compile(r"\A[a-z][a-z0-9_]{0,62}\Z")


def scratch_database_name(makerspace_id, run_id):
    run_component = re.sub(r"[^a-z0-9]", "", str(run_id).lower())
    if not run_component:
        raise TenantDumpBuildError("The Lane D run id has no safe database component.")
    prefix = f"spaceworks_dump_{int(makerspace_id)}_"
    available = 63 - len(prefix)
    if available < 12:
        raise TenantDumpBuildError("The Lane D makerspace id is too large.")
    if len(run_component) > available:
        suffix = hashlib.sha256(run_component.encode("ascii")).hexdigest()[:10]
        run_component = f"{run_component[: available - 11]}_{suffix}"
    name = f"{prefix}{run_component}"
    if not _SAFE_NAME.fullmatch(name):
        raise TenantDumpBuildError("The Lane D scratch database name is invalid.")
    return name


def _environment(database):
    env = os.environ.copy()
    values = {
        "PGDATABASE": database.get("NAME"),
        "PGUSER": database.get("USER"),
        "PGPASSWORD": database.get("PASSWORD"),
        "PGHOST": database.get("HOST"),
        "PGPORT": database.get("PORT"),
    }
    env.update({key: str(value) for key, value in values.items() if value not in (None, "")})
    return env


def _run(command, *, database, extra_env=None, cwd=None):
    environment = _environment(database)
    environment.update(extra_env or {})
    try:
        subprocess.run(
            command,
            env=environment,
            cwd=cwd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        logger.error(
            "tenant_dump.postgres_command_failed",
            extra={
                "command": Path(command[0]).name,
                "returncode": getattr(exc, "returncode", None),
                "stderr": stderr.decode("utf-8", "replace")[-4000:],
            },
        )
        raise TenantDumpBuildError("A Lane D scratch database operation failed.") from exc


def _register_alias(alias, name, database):
    connections.databases[alias] = {
        **database,
        "NAME": name,
        "CONN_MAX_AGE": 0,
    }


def _remove_alias(alias):
    connections[alias].close()
    del connections.databases[alias]
    if hasattr(connections._connections, alias):
        delattr(connections._connections, alias)


@contextmanager
def _owned_database(name, alias, *, database=None, migrate=False):
    database = database or getattr(
        settings, "TENANT_DUMP_SCRATCH_DATABASE", settings.DATABASES["default"]
    )
    major = server_major()
    _run([client_binary("createdb", major), name], database=database)
    registered = False
    try:
        _register_alias(alias, name, database)
        registered = True
        with connections[alias].cursor() as cursor:
            cursor.execute("SHOW server_version_num")
            scratch_major = int(cursor.fetchone()[0]) // 10000
        if scratch_major != major:
            raise TenantDumpBuildError(
                "The scratch PostgreSQL major does not match the target-compatible client."
            )
        if migrate:
            connections[alias].close()
            _migrate_scratch(name, database)
        yield alias, name
    finally:
        try:
            if registered:
                _remove_alias(alias)
        finally:
            _run(
                [client_binary("dropdb", major), "--if-exists", name],
                database=database,
            )


def _migrate_scratch(name, database):
    """Run migrations where even unqualified RunPython managers mean scratch."""
    scratch = {**database, "NAME": name}
    _run(
        [sys.executable, "manage.py", "migrate", "--noinput", "--verbosity", "0"],
        database=scratch,
        extra_env={
            "DATABASE_URL": _database_url(scratch),
            "CONN_MAX_AGE": "0",
        },
        cwd=settings.BASE_DIR,
    )


def _database_url(database):
    engine = database.get("ENGINE", "")
    if "postgresql" not in engine:
        raise TenantDumpBuildError("Lane D scratch storage must be PostgreSQL.")
    host = str(database.get("HOST") or "")
    if not host or host.startswith("/"):
        raise TenantDumpBuildError(
            "Lane D scratch migration requires an explicit PostgreSQL host."
        )
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    user = quote(str(database.get("USER") or ""), safe="")
    password = quote(str(database.get("PASSWORD") or ""), safe="")
    credentials = user
    if password:
        credentials += f":{password}"
    if credentials:
        credentials += "@"
    port = f":{database['PORT']}" if database.get("PORT") else ""
    path = quote(str(database["NAME"]), safe="")
    options = database.get("OPTIONS") or {}
    query = f"?{urlencode(options)}" if options else ""
    return f"postgresql://{credentials}{host}{port}/{path}{query}"


@contextmanager
def migrated_scratch_database(makerspace_id, run_id, *, database=None):
    """Create, migrate and finally drop the database owned by this run."""
    component = re.sub(r"[^a-z0-9]", "", str(run_id).lower())
    name = scratch_database_name(makerspace_id, run_id)
    alias = f"tenant_dump_{component}"
    with _owned_database(name, alias, database=database, migrate=True) as value:
        yield value


@contextmanager
def empty_verification_database(makerspace_id, run_id, *, database=None):
    """Allocate an unmigrated database into which the candidate dump is restored."""
    component = re.sub(r"[^a-z0-9]", "", str(run_id).lower())
    suffix = "verification"
    name = scratch_database_name(makerspace_id, f"{component}{suffix}")
    alias = f"tenant_dump_verify_{component}"
    with _owned_database(name, alias, database=database) as value:
        yield value


def dump_scratch_database(database_name, destination, *, database=None):
    database = database or getattr(
        settings, "TENANT_DUMP_SCRATCH_DATABASE", settings.DATABASES["default"]
    )
    _run(
        [
            client_binary("pg_dump"),
            "--format=custom",
            "--no-owner",
            "--no-acl",
            f"--dbname={database_name}",
            f"--file={Path(destination)}",
        ],
        database=database,
    )


def restore_scratch_dump(path, database_name, *, database=None):
    database = database or getattr(
        settings, "TENANT_DUMP_SCRATCH_DATABASE", settings.DATABASES["default"]
    )
    _run(
        [
            client_binary("pg_restore"),
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            f"--dbname={database_name}",
            str(path),
        ],
        database=database,
    )
