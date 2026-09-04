"""Scheduled report delivery: a recurring export and the record of each run.

A schedule names a report definition, the filters the manual export would take, a cadence
and where the file goes -- a chat destination, up to ten email addresses, or both. Each run
writes ONE `ReportDelivery` row: the private object key the file was stored under, whether
every channel accepted the link, and when the link (and the object) expire. Deliveries never
carry bytes into chat channels; they carry a short-lived signed download URL.
"""

import calendar
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models

MAX_RECIPIENT_EMAILS = 10


def validate_recipient_emails(value):
    if not isinstance(value, list):
        raise ValidationError("Recipient emails must be a list.")
    if len(value) > MAX_RECIPIENT_EMAILS:
        raise ValidationError(f"At most {MAX_RECIPIENT_EMAILS} recipient emails are allowed.")
    for item in value:
        if not isinstance(item, str):
            raise ValidationError("Recipient emails must be strings.")
        validate_email(item)


def validate_schedule_filters(value):
    if not isinstance(value, dict):
        raise ValidationError("Report filters must be an object.")


def step_cadence(moment, cadence):
    """The next occurrence after `moment` for one cadence step."""
    if cadence == ReportSchedule.Cadence.DAILY:
        return moment + timedelta(days=1)
    if cadence == ReportSchedule.Cadence.WEEKLY:
        return moment + timedelta(days=7)
    year = moment.year + (1 if moment.month == 12 else 0)
    month = 1 if moment.month == 12 else moment.month + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def advance_next_run(next_run_at, cadence, now):
    """Advance from the SCHEDULED time, not from `now`, so the clock does not drift; but
    skip every occurrence already in the past so a long outage produces one run, not a
    catch-up storm of stale reports."""
    following = step_cadence(next_run_at, cadence)
    while following <= now:
        following = step_cadence(following, cadence)
    return following


class ReportSchedule(models.Model):
    class Format(models.TextChoices):
        CSV = "csv", "CSV"
        XLSX = "xlsx", "XLSX"

    class Cadence(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="report_schedules"
    )
    report_key = models.CharField(max_length=80)
    filters = models.JSONField(default=dict, blank=True, validators=[validate_schedule_filters])
    grain = models.CharField(max_length=8, default="day")
    format = models.CharField(max_length=8, choices=Format.choices, default=Format.CSV)
    cadence = models.CharField(max_length=8, choices=Cadence.choices, default=Cadence.WEEKLY)
    next_run_at = models.DateTimeField()
    last_run_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    # SET_NULL: deleting a room must not delete the schedule's history or its email leg.
    destination = models.ForeignKey(
        "integrations.NotificationDestination",
        null=True, blank=True, on_delete=models.SET_NULL, related_name="report_schedules",
    )
    recipient_emails = models.JSONField(default=list, blank=True, validators=[validate_recipient_emails])
    # The run re-checks that this person still holds the report's action: a schedule must
    # not keep disclosing a report its creator can no longer open.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active", "next_run_at"], name="report_schedule_due_idx"),
            models.Index(fields=["makerspace", "-created_at"], name="report_schedule_ms_created_idx"),
        ]

    def __str__(self):
        return f"{self.makerspace_id}:{self.report_key} {self.cadence} ({self.format})"


class ReportDelivery(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    schedule = models.ForeignKey(ReportSchedule, on_delete=models.CASCADE, related_name="deliveries")
    # Private bucket key under `reports/<makerspace_id>/...`; blanked once the object is
    # swept after `expires_at`. Empty when the build itself failed.
    object_key = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["schedule", "-created_at"], name="report_delivery_sched_idx"),
        ]

    def __str__(self):
        return f"delivery {self.pk} of schedule {self.schedule_id}: {self.status}"
