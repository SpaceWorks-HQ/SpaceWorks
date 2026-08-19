"""Run the periodic tasks a deployment without Celery beat would otherwise never run.

**This is the one thing that stops working silently in cloud mode.** With no broker,
`CELERY_TASK_ALWAYS_EAGER` makes `.delay()` run inline, so everything a request triggers
still works and nothing looks broken -- but `CELERY_BEAT_SCHEDULE` is beat's business,
and with no beat process nothing ever fires it. `send_return_reminders` is a duty-of-care
message in the accountability flow: a member who has not returned hardware simply stops
being reminded, and the first sign is a dispute months later.

So this exists to be driven by whatever scheduler the host already has -- a platform cron
entry, a Kubernetes CronJob, systemd timer:

    */15 * * * *  python manage.py run_scheduled_tasks --due-only

Each task declares its own cadence here, mirroring `CELERY_BEAT_SCHEDULE`, and
`--due-only` makes the command idempotent under a coarser cron: a 15-minute cron running
an hourly task fires it once an hour, not four times. State lives in `PeriodicTaskRun`
rows rather than a file, because a cloud host's filesystem is not durable and two web
dynos would not share one.

Deliberately NOT an authenticated HTTP endpoint. A URL that runs jobs is a URL someone
can find, and rate-limiting it correctly is more work than a cron entry.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# (name, dotted task path, minimum minutes between runs). The cadences mirror
# CELERY_BEAT_SCHEDULE; `tests/test_scheduled_tasks.py` fails if a beat entry has no
# counterpart here, so a task added for the Celery deployment cannot silently go missing
# from the beat-less one.
SCHEDULED_TASKS = (
    (
        "audit-attestation",
        "apps.audit.tasks.run_audit_attestation_task",
        5,
    ),
    (
        "drain-password-reset-envelopes",
        "apps.accounts.tasks.drain_password_reset_envelopes_task",
        1,
    ),
    ("return-reminders", "apps.hardware_requests.tasks.send_return_reminders_task", 60),
    ("purge-auth-challenges", "apps.accounts.tasks.purge_auth_challenges_task", 24 * 60),
    # Beat runs this at a fixed hour; the beat-less runner has no wall-clock schedule, so
    # the cadence is expressed as the interval instead. Daily either way.
    (
        "refresh-github-contributions",
        "apps.makerspaces.tasks.refresh_github_contributions_task",
        24 * 60,
    ),
    # Same fixed-hour-versus-interval reasoning as above. Without this entry a beat-less
    # cloud deployment would retain expired export archives -- and the download bearer
    # tokens that reach them -- indefinitely.
    (
        "purge-expired-data-exports",
        "apps.data_export.tasks.purge_expired_exports_task",
        24 * 60,
    ),
    (
        "scheduled-deployment-backup",
        "apps.backup.tasks.scheduled_deployment_backup_task",
        24 * 60,
    ),
    (
        "purge-expired-backup-archives",
        "apps.backup.tasks.purge_expired_backup_archives_task",
        24 * 60,
    ),
    (
        "cleanup-expired-restore-rollbacks",
        "apps.backup.tasks.cleanup_expired_restore_rollbacks_task",
        24 * 60,
    ),
    (
        "cleanup-expired-tenant-import-jobs",
        "apps.tenant_migration.tasks.cleanup_expired_import_jobs_task",
        60,
    ),
    (
        "cleanup-abandoned-tenant-import-objects",
        "apps.tenant_migration.tasks.cleanup_abandoned_import_objects_task",
        60,
    ),
    (
        "resume-expired-tenant-import-finalizations",
        "apps.tenant_migration.tasks.resume_expired_finalizing_import_jobs_task",
        5,
    ),
)
if "tenant_migration" in settings.TOMBSTONED_APPS:
    SCHEDULED_TASKS = tuple(
        task for task in SCHEDULED_TASKS if ".tenant_migration." not in task[1]
    )


def _import_task(dotted_path):
    from importlib import import_module

    module_path, _, attribute = dotted_path.rpartition(".")
    return getattr(import_module(module_path), attribute)


class Command(BaseCommand):
    help = "Run periodic tasks on a deployment with no Celery beat process."

    def add_arguments(self, parser):
        parser.add_argument(
            "--due-only",
            action="store_true",
            help="Skip tasks run more recently than their declared interval.",
        )
        parser.add_argument("--task", help="Run only this task name.")

    def handle(self, *args, **options):
        from apps.operations.models_scheduling import PeriodicTaskRun

        only = options.get("task")
        now = timezone.now()
        for name, dotted_path, interval_minutes in SCHEDULED_TASKS:
            if only and name != only:
                continue
            with transaction.atomic():
                # Locked, so two cron entries or two dynos firing at the same minute run
                # the task once between them rather than twice. The reminder mail is the
                # reason this matters: sending it twice is worse than sending it late.
                # Claiming first makes this AT-MOST-ONCE, deliberately: a missed run is
                # preferable to sending the return reminder twice.
                row, _ = PeriodicTaskRun.objects.select_for_update().get_or_create(name=name)
                if options["due_only"] and not row.is_due(now, interval_minutes):
                    self.stdout.write(f"skip {name} (last run {row.last_run_at:%Y-%m-%d %H:%M})")
                    continue
                row.last_run_at = now
                row.save(update_fields=["last_run_at"])

            try:
                # Called directly, not via .delay(): under eager mode they are the
                # same thing, and with a broker configured this command should still
                # do the work rather than queue it behind a worker that may not exist.
                _import_task(dotted_path)()
            except Exception as exc:  # noqa: BLE001 - one failing task must not stop the rest
                with transaction.atomic():
                    row = PeriodicTaskRun.objects.select_for_update().get(name=name)
                    row.last_error = str(exc)[:500]
                    row.save(update_fields=["last_error"])
                self.stderr.write(self.style.ERROR(f"failed {name}: {exc}"))
                continue

            with transaction.atomic():
                row = PeriodicTaskRun.objects.select_for_update().get(name=name)
                row.last_error = ""
                row.save(update_fields=["last_error"])
            self.stdout.write(self.style.SUCCESS(f"ran {name}"))
