"""Materialize the full source database from one exported snapshot."""

import logging
import os
from pathlib import Path
import subprocess

from django.conf import settings

from apps.backup.postgres_client import client_binary

from .tenant_dump_errors import TenantDumpBuildError


logger = logging.getLogger(__name__)


def capture_database_image(snapshot_id, destination):
    destination = Path(destination)
    database = settings.DATABASES["default"]
    environment = os.environ.copy()
    values = {
        "PGDATABASE": database.get("NAME"),
        "PGUSER": database.get("USER"),
        "PGPASSWORD": database.get("PASSWORD"),
        "PGHOST": database.get("HOST"),
        "PGPORT": database.get("PORT"),
    }
    environment.update(
        {key: str(value) for key, value in values.items() if value not in (None, "")}
    )
    try:
        subprocess.run(
            [
                client_binary("pg_dump"),
                "--format=custom",
                "--no-owner",
                "--no-acl",
                f"--snapshot={snapshot_id}",
                f"--file={destination}",
            ],
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        destination.chmod(0o600)
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.error(
            "tenant_dump_capture_database_failed",
            extra={"returncode": getattr(exc, "returncode", None)},
        )
        raise TenantDumpBuildError("The Lane D database image could not be captured.") from exc
    return destination
