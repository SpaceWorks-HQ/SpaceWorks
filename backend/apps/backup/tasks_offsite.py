"""Celery entry points for offsite destinations.

Split from `tasks.py` so the push can be dispatched from the backup tasks without a
circular import. Every entry point catches its own failures: an offsite outage must
never surface as a failed backup task.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def push_offsite_backups_task(self):
    from apps.backup.offsite_push import enqueue_offsite_uploads, push_due_uploads
    from apps.backup.offsite_retention import prune_offsite_copies

    result = {"enqueued": 0, "pushed": 0, "pruned": 0}
    for name, step in (
        ("enqueued", enqueue_offsite_uploads),
        ("pushed", push_due_uploads),
        ("pruned", prune_offsite_copies),
    ):
        try:
            result[name] = step()
        except Exception:
            logger.exception("backup_offsite_step_failed", extra={"step": name})
    return result


@shared_task(bind=True, max_retries=0)
def rehydrate_backup_archive_task(self, archive_id, destination_id, actor_id=None):
    from apps.accounts.models import User
    from apps.backup.offsite_restore import rehydrate_archive

    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    try:
        return rehydrate_archive(archive_id, destination_id, actor=actor)
    except Exception:
        logger.exception(
            "backup_offsite_rehydrate_task_failed", extra={"archive_id": str(archive_id)}
        )
        return False


def dispatch_offsite_push():
    """Kick a push after a backup finished. Failure to enqueue is logged, never raised."""
    try:
        push_offsite_backups_task.delay()
    except Exception:
        logger.exception("backup_offsite_dispatch_failed")
