"""The named Celery task that executes one audit verification attempt.

Celery's generic autoretry is deliberately not used: the attempt itself appends the legal
RETRYING event and this task schedules the next delivery, so the persisted state machine
-- not the worker -- decides what a retry means. Exception text is logged, never stored.
"""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from apps.audit.verification_execution import RetryAttempt, execute_attempt, fail_attempt
from apps.audit.verification_runs import HARD_TIME_LIMIT, SOFT_TIME_LIMIT

logger = logging.getLogger(__name__)
RETRY_COUNTDOWN_SECONDS = 30


@shared_task(
    name="apps.audit.tasks.run_audit_verification",
    bind=True,
    max_retries=0,
    soft_time_limit=SOFT_TIME_LIMIT,
    time_limit=HARD_TIME_LIMIT,
)
def run_audit_verification(self, run_id):
    try:
        event = execute_attempt(run_id)
    except RetryAttempt:
        from apps.audit.verification_runs import _enqueue

        _enqueue(run_id, countdown=RETRY_COUNTDOWN_SECONDS)
        return "retrying"
    except SoftTimeLimitExceeded:
        fail_attempt(run_id, "soft_time_limit")
        return "timed_out"
    except Exception:  # noqa: BLE001 - closed failure code; text stays in the log
        logger.exception("audit_verification_task_error", extra={"run_id": run_id})
        fail_attempt(run_id, "task_error")
        return "failed"
    return event.state if event is not None else "skipped"
