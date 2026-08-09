"""Retry stuck outbound mail, for a deployment with no Celery worker.

With no broker, `CELERY_TASK_ALWAYS_EAGER` makes delivery run inline inside the request
that triggered it. That works, but it means a slow or briefly-unreachable SMTP host is
paid for by a member's request -- and when it fails there is no worker to retry it, so
the `EmailLog` row sits at FAILED until a human opens the email log and clicks Retry.

Driven by the same cron as `run_scheduled_tasks`:

    */30 * * * *  python manage.py flush_email_outbox

Routes through `retry_email_log`, never around it: that service holds the encryption
write fence, the stale-claim rule that stops an in-flight SENDING row being
double-delivered, and the audit entry. A command that re-enqueued rows directly would
skip all three, and double-delivering a return reminder is exactly the failure this is
meant to prevent.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.models import EmailLog
from apps.integrations.services import EmailRetryError, retry_email_log


class Command(BaseCommand):
    help = "Re-enqueue failed or stalled outbound email (for deployments with no worker)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age-hours",
            type=int,
            default=24,
            help="Ignore rows older than this. Default 24.",
        )
        parser.add_argument("--limit", type=int, default=100, help="Rows per run. Default 100.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options["max_age_hours"])
        # FAILED and SENDING both: `retry_email_log` refuses a SENDING row whose claim is
        # still fresh, so stalled ones are recovered and in-flight ones are left alone.
        # Bounded and oldest-first, so one poisonous row cannot starve the rest and a
        # backlog drains in cron-sized bites instead of one enormous run.
        rows = EmailLog.objects.filter(
            status__in=[EmailLog.Status.FAILED, EmailLog.Status.SENDING],
            updated_at__gte=cutoff,
        ).order_by("updated_at")[: options["limit"]]

        retried = skipped = 0
        for log in rows:
            try:
                retry_email_log(None, log)
            except EmailRetryError:
                # Not an error: a fresh SENDING claim or a row with no stored content is
                # correctly left alone, and every run will meet some of both.
                skipped += 1
                continue
            retried += 1
        self.stdout.write(self.style.SUCCESS(f"retried {retried}, skipped {skipped}"))
