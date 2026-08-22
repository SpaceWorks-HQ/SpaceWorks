"""Choosing the PostgreSQL client binaries that match this deployment's server.

The image ships two client majors deliberately, because the two directions have
opposite constraints:

* ``pg_dump`` must be at least as new as any *source* server tenant migration
  reads (14-17), so the newest client is the one on ``PATH``.
* Anything that dumps or restores *this* deployment has the reverse requirement.
  A custom-format archive written by ``pg_dump`` 17 carries file-header version
  1.16, which ``pg_restore`` 16 refuses outright, and ``pg_restore`` 17+ emits an
  unconditional ``SET transaction_timeout = 0;`` -- a GUC that does not exist
  before 17, so a pre-17 server rejects it and ``--exit-on-error`` aborts.

So the deployment's own backup, restore and readable-main projection all resolve
their client from this module rather than trusting ``PATH``. Getting this wrong
is not a warning: it produces archives the shipped restore path cannot read.
"""

from functools import lru_cache
from pathlib import Path
import re
import shutil
import subprocess

from django.db import connections

# Where a distribution package puts one major version's client binaries.
_VERSIONED_CLIENT_DIRS = (
    "/usr/lib/postgresql/{major}/bin",  # Debian, Ubuntu, PGDG apt
    "/usr/pgsql-{major}/bin",  # RHEL, Rocky, PGDG yum
)


class PostgresClientUnavailable(RuntimeError):
    """No client matching the server's major version is installed."""


def server_major():
    """Major version of the PostgreSQL server this deployment runs on."""
    with connections["default"].cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        return int(cursor.fetchone()[0]) // 10000


@lru_cache(maxsize=None)
def _binary_major(path):
    """Major version a client binary reports, or None when it cannot be read."""
    try:
        completed = subprocess.run(
            [path, "--version"], capture_output=True, check=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"\b(\d+)\.\d+", completed.stdout)
    return int(match.group(1)) if match else None


def client_binary(tool, major=None):
    """Absolute path to `tool` for the server's major version.

    Fails closed rather than falling back to whatever is on PATH: a mismatched
    client does not degrade gracefully, it writes archives the restore path
    cannot read.
    """
    major = server_major() if major is None else major
    for template in _VERSIONED_CLIENT_DIRS:
        candidate = Path(template.format(major=major)) / tool
        if candidate.exists():
            return str(candidate)
    on_path = shutil.which(tool)
    if on_path and _binary_major(on_path) == major:
        return on_path
    raise PostgresClientUnavailable(
        f"No PostgreSQL {major} client is installed, so {tool} cannot run "
        f"against this deployment's server. Install postgresql-client-{major}; "
        f"the client major must match the database server."
    )
