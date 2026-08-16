from celery import shared_task

from apps.tenant_migration.services_import_job import cleanup_expired_import_jobs


@shared_task(name="apps.tenant_migration.tasks.cleanup_expired_import_jobs_task")
def cleanup_expired_import_jobs_task():
    return cleanup_expired_import_jobs()
