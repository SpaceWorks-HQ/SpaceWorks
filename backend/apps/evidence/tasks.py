from celery import shared_task

from apps.evidence.abandoned_upload_cleanup import sweep_abandoned_evidence_uploads
from apps.evidence.abandoned_upload_reconciliation import reconcile_receipts
from apps.evidence.services_retention import sweep_evidence_retention


@shared_task(name="apps.evidence.tasks.sweep_evidence_retention_task")
def sweep_evidence_retention_task(dry_run=False, batch_size=None):
    return sweep_evidence_retention(
        dry_run=bool(dry_run),
        batch_size=batch_size,
    )


@shared_task(name="apps.evidence.tasks.cleanup_abandoned_evidence_uploads_task")
def cleanup_abandoned_evidence_uploads_task(dry_run=False, batch_size=None):
    # Receipts from earlier successful deletions are reconciled FIRST and regardless of
    # the cleanup switches; dry-run only reports their backlog.
    reconciliation = reconcile_receipts(dry_run=bool(dry_run), batch_size=batch_size)
    cleanup = sweep_abandoned_evidence_uploads(dry_run=bool(dry_run), batch_size=batch_size)
    return {"reconciliation": reconciliation, "cleanup": cleanup}
