"""Request/response schemas for staff audit verification runs.

Staff responses carry only aggregate coverage. The closed ``failure_code`` and the two
diagnostic coordinates (first offending row id / batch sequence) are added only for a
superuser; ordinary staff could otherwise use them to locate a tampered row through the
API whatever the UI renders.
"""

from django.urls import reverse
from rest_framework import serializers

from apps.admin_api.serializers_audit import AuditLogFilterSerializer
from apps.audit.models import AuditVerificationRunEvent

COUNT_FIELDS = (
    "row_count", "mac_valid_count", "unattested_count", "mac_invalid_count",
    "mac_unavailable_count", "unbatched_count", "local_batch_verified_count",
    "batch_invalid_count", "batch_unavailable_count", "externally_anchored_count",
)
DIAGNOSTIC_FIELDS = ("failure_code", "first_audit_log_id", "first_batch_seq")


class VerificationRequestSerializer(AuditLogFilterSerializer):
    """The audit-list filters, minus ``makerspace`` (it comes from the path)."""

    makerspace = None


class VerificationAcceptedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.CharField()
    deduplicated = serializers.BooleanField()
    status_url = serializers.CharField()


class VerificationFiltersSerializer(serializers.Serializer):
    action = serializers.CharField(source="action_filter", allow_blank=True)
    target_type = serializers.CharField(source="target_type_filter", allow_blank=True)
    target_id = serializers.CharField(source="target_id_filter", allow_blank=True)
    actor = serializers.IntegerField(source="actor_filter", allow_null=True)
    start = serializers.DateTimeField(source="start_at", allow_null=True)
    end = serializers.DateTimeField(source="end_at", allow_null=True)


class VerificationCoverageSerializer(serializers.Serializer):
    attempt = serializers.IntegerField()
    chain_status = serializers.ChoiceField(choices=AuditVerificationRunEvent.ChainStatus.choices)
    anchor_status = serializers.ChoiceField(choices=AuditVerificationRunEvent.AnchorStatus.choices)
    # Counts of SELECTED ROWS per dimension. They overlap by design and never sum.
    row_count = serializers.IntegerField()
    mac_valid_count = serializers.IntegerField()
    unattested_count = serializers.IntegerField()
    mac_invalid_count = serializers.IntegerField()
    mac_unavailable_count = serializers.IntegerField()
    unbatched_count = serializers.IntegerField()
    local_batch_verified_count = serializers.IntegerField()
    batch_invalid_count = serializers.IntegerField()
    batch_unavailable_count = serializers.IntegerField()
    externally_anchored_count = serializers.IntegerField()


class VerificationRunSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    makerspace = serializers.IntegerField(source="makerspace_id")
    state = serializers.ChoiceField(choices=AuditVerificationRunEvent.State.choices)
    terminal = serializers.BooleanField()
    snapshot_max_id = serializers.IntegerField()
    filters = VerificationFiltersSerializer()
    coverage = VerificationCoverageSerializer()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    status_url = serializers.CharField()
    failure_code = serializers.CharField(
        required=False, help_text="Superuser only: closed operational failure code."
    )
    first_audit_log_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Superuser only diagnostic."
    )
    first_batch_seq = serializers.IntegerField(
        required=False, allow_null=True, help_text="Superuser only diagnostic."
    )


def status_url(run):
    return reverse("admin-audit-verification-detail", args=[run.makerspace_id, run.pk])


def run_payload(run, event, *, superuser):
    payload = {
        "id": run.pk,
        "makerspace": run.makerspace_id,
        "state": event.state,
        "terminal": event.state in AuditVerificationRunEvent.TERMINAL_STATES,
        "snapshot_max_id": run.snapshot_max_id,
        "filters": VerificationFiltersSerializer(run).data,
        "coverage": {
            "attempt": event.attempt,
            "chain_status": event.chain_status,
            "anchor_status": event.anchor_status,
            **{name: getattr(event, name) for name in COUNT_FIELDS},
        },
        "created_at": run.created_at,
        "updated_at": event.created_at,
        "status_url": status_url(run),
    }
    if superuser:
        payload.update({name: getattr(event, name) for name in DIAGNOSTIC_FIELDS})
    return payload
