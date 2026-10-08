from celery import shared_task

from apps.backup.services import purge_expired_archives, run_archive, schedule_deployment_backup
from apps.backup.models import BackupArchive, BackupRun
from apps.backup.object_restore import cleanup_expired_rollback_objects
from apps.backup.custody_alarms import deliver_archive_custody_alarms
from apps.backup.reconciliation import reconcile_artifact_uploads
from apps.backup.tenant_exit_custody_alarms import (
    deliver_tenant_exit_custody_alarms,
)


from apps.backup.tasks_offsite import (  # noqa: E402,F401  (task registration)
    dispatch_offsite_push,
    push_offsite_backups_task,
    rehydrate_backup_archive_task,
)


@shared_task(bind=True, max_retries=0)
def run_backup_archive_task(self, archive_id):
    archive = run_archive(archive_id)
    available = bool(archive and archive.status == BackupArchive.Status.AVAILABLE)
    if available and archive.scope == BackupArchive.Scope.DEPLOYMENT:
        # After the build released the deployment operation lock: the offsite push
        # must never hold it, and its failure must never fail this task.
        dispatch_offsite_push()
    return available


@shared_task(bind=True, max_retries=0)
def scheduled_deployment_backup_task(self):
    run = schedule_deployment_backup()
    if run is not None:
        dispatch_offsite_push()
    return bool(run and run.status == BackupRun.Status.COMPLETE)


@shared_task(bind=True, max_retries=0)
def purge_expired_backup_archives_task(self):
    return purge_expired_archives()


@shared_task(bind=True, max_retries=0)
def cleanup_expired_restore_rollbacks_task(self):
    return cleanup_expired_rollback_objects()


@shared_task(bind=True, max_retries=0)
def deliver_archive_custody_alarms_task(self, makerspace_id=None):
    return deliver_archive_custody_alarms(makerspace_id=makerspace_id)


@shared_task(bind=True, max_retries=0)
def deliver_tenant_exit_custody_alarms_task(self, makerspace_id=None):
    return deliver_tenant_exit_custody_alarms(makerspace_id=makerspace_id)


@shared_task(bind=True, max_retries=0)
def reconcile_backup_artifacts_task(self):
    return reconcile_artifact_uploads()
