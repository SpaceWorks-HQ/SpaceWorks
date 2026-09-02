from celery import shared_task

from apps.evidence.services_retention import sweep_evidence_retention


@shared_task(name="apps.evidence.tasks.sweep_evidence_retention_task")
def sweep_evidence_retention_task(dry_run=False, batch_size=None):
    return sweep_evidence_retention(
        dry_run=bool(dry_run),
        batch_size=batch_size,
    )
