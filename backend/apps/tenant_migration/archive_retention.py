"""Post-commit, best-effort retention for staged encrypted import archives."""

import logging
from pathlib import Path

from django.db import transaction


logger = logging.getLogger(__name__)


def schedule_import_archive_unlink(path, job_id):
    if not path:
        return

    def unlink():
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            logger.exception(
                "tenant_import_archive_unlink_failed",
                extra={"job_id": str(job_id), "archive_path": str(path)},
            )

    # A crash after the database commit but before this callback leaves a repairable
    # orphan file discoverable from retention logs, never a rolled-back row naming a
    # file that was prematurely deleted.
    transaction.on_commit(unlink)
