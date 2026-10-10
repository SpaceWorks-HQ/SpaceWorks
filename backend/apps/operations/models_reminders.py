"""Source-local reminder coordination; domain subjects remain owned by their apps."""

from django.db import models


class ReminderSchedule(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        CLAIMED = "claimed", "Claimed"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="reminder_schedules"
    )
    source = models.CharField(max_length=80)
    subject = models.CharField(max_length=160)
    kind = models.CharField(max_length=80)
    offset_seconds = models.IntegerField()
    due_at = models.DateTimeField()
    remind_at = models.DateTimeField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    claim_token = models.UUIDField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "source", "subject", "kind", "offset_seconds"],
                name="uniq_reminder_subject_kind_step",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state="pending", claim_token__isnull=True,
                             claimed_at__isnull=True, completed_at__isnull=True)
                    | models.Q(state="claimed", claim_token__isnull=False,
                               claimed_at__isnull=False, completed_at__isnull=True)
                    | models.Q(state__in=["completed", "failed"], claim_token__isnull=False,
                               claimed_at__isnull=False, completed_at__isnull=False)
                ),
                name="reminder_claim_state_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["makerspace", "source", "state", "remind_at"],
                         name="reminder_ms_source_due_idx"),
        ]
