from celery import shared_task

from apps.backup.services import purge_expired_archives, run_archive, schedule_deployment_backup
from apps.backup.models import BackupArchive
from apps.backup.object_restore import cleanup_expired_rollback_objects
from apps.backup.custody_alarms import deliver_archive_custody_alarms


@shared_task(bind=True, max_retries=0)
def run_backup_archive_task(self, archive_id):
    archive = run_archive(archive_id)
    return bool(archive and archive.status == BackupArchive.Status.AVAILABLE)


@shared_task(bind=True, max_retries=0)
def scheduled_deployment_backup_task(self):
    archive = schedule_deployment_backup()
    return bool(archive and archive.status == BackupArchive.Status.AVAILABLE)


@shared_task(bind=True, max_retries=0)
def purge_expired_backup_archives_task(self):
    return purge_expired_archives()


@shared_task(bind=True, max_retries=0)
def cleanup_expired_restore_rollbacks_task(self):
    return cleanup_expired_rollback_objects()


@shared_task(bind=True, max_retries=0)
def deliver_archive_custody_alarms_task(self, makerspace_id=None):
    return deliver_archive_custody_alarms(makerspace_id=makerspace_id)
