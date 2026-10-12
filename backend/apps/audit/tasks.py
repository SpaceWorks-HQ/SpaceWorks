from celery import shared_task

from apps.audit.batches import run_audit_attestation
from apps.audit.tasks_verification import run_audit_verification  # noqa: F401 - autodiscovery


@shared_task(name="apps.audit.tasks.run_audit_attestation_task")
def run_audit_attestation_task():
    return run_audit_attestation()
