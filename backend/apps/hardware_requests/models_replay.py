"""Short-lived replay coordination; payloads, QR bytes and PII are never stored."""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .replay_resolution_constraints import resolution_constraints


class ReplayCommand(models.Model):
    class Resolution(models.TextChoices):
        ACKNOWLEDGED_NO_CHANGE = "acknowledged_no_change"
        REPLACED_ONLINE = "replaced_online"

    class State(models.TextChoices):
        PREPARED = "prepared"
        CLAIMED = "claimed"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    station = models.ForeignKey("makerspaces.Station", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operator_lease_id = models.UUIDField()
    station_session_id = models.UUIDField()
    station_version = models.PositiveIntegerField()
    client_command_id = models.UUIDField()
    payload_fingerprint = models.CharField(max_length=64)
    operation_kind = models.CharField(max_length=24)
    operation_version = models.PositiveIntegerField()
    aggregate_id = models.UUIDField()
    sequence = models.PositiveIntegerField()
    predecessor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="successors",
    )
    state = models.CharField(max_length=12, choices=State.choices, default=State.PREPARED)
    claim_token = models.UUIDField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_attempts = models.PositiveIntegerField(default=0)
    client_created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=64, null=True, blank=True)
    failure_detail = models.CharField(max_length=200, null=True, blank=True)
    subject_request = models.ForeignKey(
        "hardware_requests.HardwareRequest", null=True, blank=True,
        on_delete=models.PROTECT, related_name="subject_replays",
    )
    subject_loan = models.ForeignKey(
        "hardware_requests.PublicToolLoan", null=True, blank=True,
        on_delete=models.PROTECT, related_name="subject_replays",
    )
    evidence = models.ForeignKey("evidence.EvidencePhoto", null=True, blank=True, on_delete=models.PROTECT)
    result_request = models.ForeignKey(
        "hardware_requests.HardwareRequest", null=True, blank=True,
        on_delete=models.PROTECT, related_name="result_replays",
    )
    result_loan = models.ForeignKey(
        "hardware_requests.PublicToolLoan", null=True, blank=True,
        on_delete=models.PROTECT, related_name="result_replays",
    )
    result_return_event = models.ForeignKey(
        "hardware_requests.ReturnEvent", null=True, blank=True, on_delete=models.PROTECT,
    )
    resolution_code = models.CharField(max_length=24, choices=Resolution.choices, null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="resolved_kiosk_replays")
    resolved_at = models.DateTimeField(null=True, blank=True)
    replacement_command = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="resolved_failures")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("station", "station_session_id", "client_command_id"),
                name="replay_owner_command_unique",
            ),
            models.UniqueConstraint(
                fields=("station", "station_session_id", "aggregate_id", "sequence"),
                name="replay_stream_position_unique",
            ),
            models.CheckConstraint(condition=models.Q(sequence__gt=0, operation_version__gt=0),
                                   name="replay_positive_protocol"),
            models.CheckConstraint(
                condition=(models.Q(state="claimed", claim_token__isnull=False, claimed_at__isnull=False)
                           | (~models.Q(state="claimed") & models.Q(claim_token__isnull=True, claimed_at__isnull=True))),
                name="replay_claim_consistent",
            ),
            models.CheckConstraint(
                condition=(models.Q(state__in=("succeeded", "failed"), completed_at__isnull=False)
                           | models.Q(state__in=("prepared", "claimed"), completed_at__isnull=True)),
                name="replay_completion_consistent",
            ),
            models.CheckConstraint(
                condition=(models.Q(state="failed", failure_code__isnull=False, failure_detail__isnull=False)
                           | (~models.Q(state="failed") & models.Q(failure_code__isnull=True, failure_detail__isnull=True))),
                name="replay_failure_consistent",
            ),
        ] + resolution_constraints()
        indexes = [
            models.Index(fields=("state", "expires_at"), name="replay_state_expiry_idx"),
            models.Index(fields=("station", "station_session_id", "aggregate_id"), name="replay_stream_idx"),
            models.Index(fields=("state", "claimed_at"), name="replay_stale_claim_idx"),
        ]

    def clean(self):
        super().clean()
        if self.station_id and self.makerspace_id != self.station.makerspace_id:
            raise ValidationError("Replay and Station must belong to the same makerspace.")
        for field in ("subject_request", "subject_loan", "evidence", "result_request", "result_loan", "result_return_event"):
            if getattr(self, f"{field}_id") and getattr(self, field).makerspace_id != self.makerspace_id:
                raise ValidationError("Replay references must belong to the same makerspace.")
        if self.predecessor_id:
            previous = self.predecessor
            if (previous.station_id != self.station_id or previous.station_session_id != self.station_session_id
                    or previous.aggregate_id != self.aggregate_id or previous.sequence != self.sequence - 1
                    or previous.actor_id != self.actor_id or previous.operator_lease_id != self.operator_lease_id):
                raise ValidationError("Replay predecessor must be the immediate owned stream position.")
        elif self.sequence != 1:
            raise ValidationError("Later stream positions require a predecessor.")

    def save(self, *args, **kwargs):
        self.clean()
        if not self._state.adding:
            immutable = ("makerspace_id", "station_id", "actor_id", "operator_lease_id", "station_session_id",
                         "station_version", "client_command_id", "payload_fingerprint", "operation_kind",
                         "operation_version", "aggregate_id", "sequence", "predecessor_id", "client_created_at", "expires_at")
            original = type(self).objects.filter(pk=self.pk).values(*immutable).first()
            if original and any(original[key] != getattr(self, key) for key in immutable):
                raise ValidationError("Replay ownership and canonical identity are immutable.")
            terminal = ("state", "payload_fingerprint", "evidence_id", "failure_code", "failure_detail",
                        "created_at", "updated_at", "completed_at", "subject_request_id", "subject_loan_id",
                        "result_request_id", "result_loan_id", "result_return_event_id")
            review = ("resolution_code", "resolved_by_id", "resolved_at", "replacement_command_id")
            persisted = type(self).objects.filter(pk=self.pk).values(*terminal, *review).first()
            if persisted and persisted["state"] in ("failed", "succeeded"):
                if any(persisted[key] != getattr(self, key) for key in terminal):
                    raise ValidationError("A terminal replay attempt is immutable.")
                if persisted["resolution_code"] and any(persisted[key] != getattr(self, key) for key in review):
                    raise ValidationError("Replay review metadata is immutable.")
                # Preserve auto_now even when a caller performs an ordinary save.
                kwargs["update_fields"] = review
        return super().save(*args, **kwargs)
