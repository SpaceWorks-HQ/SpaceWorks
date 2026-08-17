from celery import shared_task

from apps.tenant_migration.services_import_job import (
    cleanup_expired_import_jobs,
    run_import_job,
)
from apps.tenant_migration.services_export_job import run_migration_export_job


@shared_task(name="apps.tenant_migration.tasks.cleanup_expired_import_jobs_task")
def cleanup_expired_import_jobs_task():
    return cleanup_expired_import_jobs()


@shared_task(name="apps.tenant_migration.tasks.run_migration_export_job_task")
def run_migration_export_job_task(job_id):
    return run_migration_export_job(job_id)


@shared_task(name="apps.tenant_migration.tasks.run_import_job_task")
def run_import_job_task(job_id, actor_id, target_identity=None):
    return run_import_job(job_id, actor_id=actor_id, target_identity=target_identity)
