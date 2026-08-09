"""Last-run state for the beat-less scheduler.

A table rather than a file, for two reasons a cloud deployment makes unavoidable: a
platform dyno's filesystem is not durable across restarts, and two web processes running
the same cron would not share one. Celery beat has the same problem and solves it with an
explicit `--schedule` path on a named volume; this is the equivalent for a deployment
that has no beat process to give a volume to.
"""

from datetime import timedelta

from django.db import models
from django.utils import timezone


class PeriodicTaskRun(models.Model):
    name = models.CharField(max_length=100, unique=True)
    last_run_at = models.DateTimeField(default=timezone.now)
    last_error = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        verbose_name = "periodic task run"
        verbose_name_plural = "periodic task runs"

    def __str__(self):
        return f"{self.name} @ {self.last_run_at:%Y-%m-%d %H:%M}"

    def is_due(self, now, interval_minutes):
        """Whether enough time has passed to run again.

        `last_run_at` defaults to now on creation, so a freshly created row is NOT due.
        That is deliberate: a new deployment should not fire every task the first time
        cron runs, which would send a batch of reminders for hardware nobody has had time
        to return yet.
        """
        return now - self.last_run_at >= timedelta(minutes=interval_minutes)
